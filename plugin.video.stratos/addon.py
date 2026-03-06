# -*- coding: utf-8 -*-
import sys
import urllib.parse
import requests
import re
from bs4 import BeautifulSoup
import xbmcgui
import xbmcplugin
import xbmc
from concurrent.futures import ThreadPoolExecutor

# --- Configuration ---
HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else -1
BASE_URL = "https://flemmix.rent"
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# --- Menus ---

def main_menu():
    add_item("[COLOR yellow]🔍 RECHERCHE[/COLOR]", "search", "")
    add_item("[COLOR white]🎬 FILMS[/COLOR]", "list_movies", f"{BASE_URL}/film-en-streaming/")
    add_item("[COLOR lightblue]📺 SÉRIES[/COLOR]", "list_movies", f"{BASE_URL}/serie-en-streaming/")
    add_item("[COLOR orange]📂 GENRES[/COLOR]", "genres_menu", "")
    xbmcplugin.endOfDirectory(HANDLE)

def genres_menu():
    add_item("[COLOR cyan]🏠 RETOUR AU MENU PRINCIPAL[/COLOR]", "main", "")
    genres = [
        ("🎭 Action", "/film-en-streaming/action/"), ("💥 Animation", "/film-en-streaming/animation/"),
        ("🥋 Arts Martiaux", "/film-en-streaming/arts-martiaux/"), ("🧗 Aventure", "/film-en-streaming/aventure/"),
        ("📜 Biopic", "/film-en-streaming/biopic/"), ("😂 Comédie", "/film-en-streaming/comedie/"),
        ("🧛 Horreur", "/film-en-streaming/epouvante-horreur/"), ("🏛️ Drame", "/film-en-streaming/drame/"),
        ("🪄 Fantastique", "/film-en-streaming/fantastique/"), ("🚔 Policier", "/film-en-streaming/policier/"),
        ("🚀 Science Fiction", "/film-en-streaming/science-fiction/"), ("🕵️ Thriller", "/film-en-streaming/thriller/")
    ]
    for name, path in genres:
        add_item(name, "list_movies", BASE_URL + path)
    xbmcplugin.endOfDirectory(HANDLE)

def add_item(name, action, url, thumb="", is_folder=True, plot=""):
    li = xbmcgui.ListItem(label=name)
    if thumb: li.setArt({'thumb': thumb, 'icon': thumb, 'poster': thumb, 'fanart': thumb})
    if plot:
        info = li.getVideoInfoTag()
        info.setPlot(plot)
    q = urllib.parse.urlencode({'action': action, 'url': url})
    xbmcplugin.addDirectoryItem(HANDLE, f"{sys.argv[0]}?{q}", li, is_folder)

# --- Scraping ---

def get_html(url, post_data=None):
    try:
        headers = {'User-Agent': USER_AGENT, 'Referer': BASE_URL}
        r = requests.post(url, headers=headers, data=post_data, timeout=10) if post_data else requests.get(url, headers=headers, timeout=10)
        r.encoding = 'utf-8'
        return r.text
    except: return None

def fetch_synopsis(movie_url):
    html = get_html(movie_url)
    if not html: return ""
    soup = BeautifulSoup(html, 'html.parser')
    desc_block = soup.find('div', class_='screenshots-full')
    if desc_block:
        text = desc_block.get_text(" ", strip=True)
        if "Synopsis:" in text: return text.split("Synopsis:")[-1].strip()
    return "Cliquez pour voir les sources."

def list_movies(url, post_data=None):
    xbmcplugin.setContent(HANDLE, 'movies')
    add_item("[COLOR cyan]🏠 RETOUR AU MENU PRINCIPAL[/COLOR]", "main", "")

    html = get_html(url, post_data)
    if not html: 
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.find_all('div', class_='mov')
    
    if not post_data and len(items) > 42:
        items = items[30:-12]

    movie_list = []
    for item in items:
        link_tag = item.find('a', class_='mov-t')
        if link_tag:
            title = re.sub(r'(?i)flemmix|en streaming|vf|vostfr', '', link_tag.get_text(strip=True)).strip(' -:').strip()
            href = link_tag['href']
            img = item.find('img')
            thumb = (BASE_URL + img['src']) if img and img['src'].startswith('/') else (img['src'] if img else "")
            movie_list.append({'title': title, 'url': href, 'thumb': thumb})

    with ThreadPoolExecutor(max_workers=10) as executor:
        synopses = list(executor.map(fetch_synopsis, [m['url'] for m in movie_list]))

    for i, m in enumerate(movie_list):
        li = xbmcgui.ListItem(label=m['title'])
        li.setArt({'thumb': m['thumb'], 'poster': m['thumb'], 'fanart': m['thumb']})
        info = li.getVideoInfoTag()
        info.setPlot(synopses[i])
        info.setMediaType('movie')
        q = urllib.parse.urlencode({'action': 'select_source', 'url': m['url'], 'title': m['title'], 'thumb': m['thumb']})
        xbmcplugin.addDirectoryItem(HANDLE, f"{sys.argv[0]}?{q}", li, True)

    # --- PAGINATION & SAUT DE PAGE ---
    next_page_url = None
    nav = soup.find('div', class_='navigation')
    if nav:
        next_link = nav.find('a', string=re.compile(r'Suivant|Next|>>|>', re.IGNORECASE))
        if next_link and next_link.has_attr('href'):
            next_page_url = next_link['href']
    
    if not next_page_url and not post_data:
        match = re.search(r'/page/(\d+)', url)
        curr = int(match.group(1)) if match else 1
        next_page_url = url.replace(f'/page/{curr}', f'/page/{curr + 1}') if match else url.rstrip('/') + '/page/2/'

    if next_page_url:
        if not next_page_url.startswith('http'): next_page_url = BASE_URL + next_page_url
        add_item("[COLOR green][B]➡ PAGE SUIVANTE[/B][/COLOR]", "list_movies", next_page_url)
        
        if not post_data:
            q_jump = urllib.parse.urlencode({'action': 'jump_page', 'url': url})
            li_jump = xbmcgui.ListItem(label="[COLOR yellow]🔢 ALLER À LA PAGE...[/COLOR]")
            xbmcplugin.addDirectoryItem(HANDLE, f"{sys.argv[0]}?{q_jump}", li_jump, True)

    xbmcplugin.endOfDirectory(HANDLE)

def jump_page(url):
    """Ouvre le pavé numérique direct"""
    dialog = xbmcgui.Dialog()
    page_num = dialog.numeric(0, 'Numéro de page :')
    if page_num:
        base = re.sub(r'/page/\d+/?', '/', url).rstrip('/')
        new_url = f"{base}/page/{page_num}/"
        list_movies(new_url)

def select_source(url, title, thumb):
    html = get_html(url)
    if not html: return
    plot = fetch_synopsis(url)
    servers = {'voe.sx': 'VOE', 'christopheruntilpoint.com': 'VOE', 'uqload': 'UQLOAD', 'vidmoly': 'VIDMOLY', 'dsvplay': 'DDSTREAM', 'luluvdo': 'LULUTV', 'waaw': 'NETU', 'minochinos': 'FILELIONS'}
    matches = re.findall(r"loadVideo\('(.+?)'\)", html)
    for v_url in set(matches):
        if v_url.startswith('//'): v_url = "https:" + v_url
        srv_name = "SOURCE"
        for key, name in servers.items():
            if key in v_url.lower(): srv_name = name; break
        li = xbmcgui.ListItem(label=f"▶ {srv_name}")
        li.setArt({'thumb': thumb, 'poster': thumb})
        li.setProperty('IsPlayable', 'true')
        info = li.getVideoInfoTag()
        info.setPlot(plot)
        q = urllib.parse.urlencode({'action': 'play', 'url': v_url})
        xbmcplugin.addDirectoryItem(HANDLE, f"{sys.argv[0]}?{q}", li, False)
    xbmcplugin.endOfDirectory(HANDLE)

def play_video(url):
    try:
        import resolveurl
        res = resolveurl.resolve(url)
        if res: xbmcplugin.setResolvedUrl(HANDLE, True, xbmcgui.ListItem(path=res))
    except: pass

def search():
    kb = xbmc.Keyboard('', 'Recherche')
    kb.doModal()
    if kb.isConfirmed() and kb.getText():
        data = {'do': 'search', 'subaction': 'search', 'story': kb.getText()}
        list_movies(f"{BASE_URL}/index.php?do=search", data)

# --- Router ---
params = dict(urllib.parse.parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
action = params.get('action')
if not action or action == 'main': main_menu()
elif action == 'genres_menu': genres_menu()
elif action == 'list_movies': list_movies(params.get('url'))
elif action == 'jump_page': jump_page(params.get('url'))
elif action == 'select_source': select_source(params.get('url'), params.get('title'), params.get('thumb'))
elif action == 'play': play_video(params.get('url'))
elif action == 'search': search()
