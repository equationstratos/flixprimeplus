# -*- coding: utf-8 -*-
import sys
import os
import urllib.parse
import requests
import re
import hashlib
import json
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import xbmcgui
import xbmcplugin
import xbmc
import xbmcaddon
import xbmcvfs

# --- Configuration ---
ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo('path')
ADDON_PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else -1
BASE_URL = "https://flemmix.voto"
ANIME_URL = "https://french-anime.com"
URL_SERVEUR = "https://semiconventional-gleesomely-rueben.ngrok-free.dev/flixprimeplus/check.php"

if not xbmcvfs.exists(ADDON_PROFILE):
    xbmcvfs.mkdir(ADDON_PROFILE)

CACHE_FILE = os.path.join(ADDON_PROFILE, "synopsis_cache.json")
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

session = requests.Session()
session.headers.update(HEADERS)

# --- Gestion du Cache ---
def load_cache():
    if xbmcvfs.exists(CACHE_FILE):
        try:
            f = xbmcvfs.File(CACHE_FILE, 'r')
            content = f.read()
            f.close()
            return json.loads(content) if content else {}
        except: return {}
    return {}

def save_cache(data):
    try:
        f = xbmcvfs.File(CACHE_FILE, 'w')
        f.write(json.dumps(data))
        f.close()
    except: pass

SYNOPSIS_CACHE = load_cache()

def vider_cache():
    try:
        if xbmcvfs.exists(CACHE_FILE):
            xbmcvfs.delete(CACHE_FILE)
            global SYNOPSIS_CACHE
            SYNOPSIS_CACHE = {}
            xbmcgui.Dialog().notification("Nettoyage", "Cache vidé !", xbmcgui.NOTIFICATION_INFO, 3000)
            xbmc.executebuiltin("Container.Refresh")
    except: pass

# --- Utilitaires ---
def get_art(filename):
    path = os.path.join(ADDON_PATH, 'resources', 'art', filename)
    return path if os.path.exists(path) else os.path.join(ADDON_PATH, 'icon.png')

FANART_GLOBAL = get_art("fanart2.png")

# --- Utilitaires de Vue & Sortie ---
def force_view():
    # 1. On récupère l'ID sauvegardé dans le XML (54 par défaut)
    view_id = ADDON.getSetting('default_view') or "54"
    
    # 2. On définit le type de contenu
    xbmcplugin.setContent(HANDLE, 'movies')
    
    # 3. On applique la vue sans attendre (plus fluide)
    xbmc.executebuiltin(f"Container.SetViewMode({view_id})")

def quitter_addon():
    # La méthode la plus efficace pour fermer un addon proprement
    xbmc.executebuiltin("ActivateWindow(home)")

# --- Navigation Spécifique : Go To Page (CORRIGÉ) ---
def go_to_page(url, mode_type, action_name, post_data=None):
    # 1. On s'assure que Kodi n'est pas "occupé"
    xbmc.sleep(200)
    
    # 2. Appel direct du Pavé Numérique (type 0 = Clavier numérique)
    # .numeric(type, titre, valeur_par_defaut)
    dialog = xbmcgui.Dialog()
    kb = dialog.numeric(0, "Aller à la page", "")
    
    # Si l'utilisateur fait "Retour" ou laisse vide, kb sera None ou vide
    if not kb or kb == "":
        return

    try:
        page = int(kb)
    except ValueError:
        return

    if page <= 1: 
        page = 1

    params = {'action': action_name, 'mode_type': mode_type}

    if post_data:
        # Gestion Recherche
        p_dict = dict(urllib.parse.parse_qsl(post_data))
        p_dict['search_start'] = str(page) if mode_type == "animes" else str(page - 1)
        params['url'] = url
        params['post_data'] = urllib.parse.urlencode(p_dict)
    else:
        # Gestion Listing (Nettoyage de l'URL pour éviter l'empilement)
        clean_url = re.sub(r'/page/\d+/?', '', url).rstrip('/')
        params['url'] = f"{clean_url}/page/{page}/"

    # 3. On génère l'URL finale
    target_url = f"{sys.argv[0]}?{urllib.parse.urlencode(params)}"
    
    # 4. On force la mise à jour de l'affichage
    xbmc.executebuiltin(f"Container.Update({target_url})")
# --- Extraction des Synopsis ---
def extract_movie_synopsis(soup):
    try:
        synop_h3 = soup.find('h3', class_='synop')
        if synop_h3:
            text = synop_h3.parent.get_text(strip=True)
            text = re.sub(r'Synopsis\s*:', '', text, flags=re.I)
            text = re.sub(r'^.*?Streaming Complet:\s*', '', text, flags=re.I)
            return " ".join(text.split()).strip()
    except: pass
    return None

def extract_series_synopsis(soup):
    try:
        container = soup.find('span', itemprop='description') or \
                    soup.find('div', class_='mov-desc') or \
                    soup.find('div', class_='mov-desc-text')
        if container:
            text = container.get_text(separator=' ', strip=True)
            text = re.sub(r'^.*?Streaming Complet:\s*', '', text, flags=re.I)
            return " ".join(text.split()).strip()
    except: pass
    return None

def get_single_synopsis(url):
    try:
        r = session.get(url, timeout=5).text
        soup = BeautifulSoup(r, 'html.parser')
        
        # 1. EXTRACTION DU SYNOPSIS (Logique existante optimisée)
        synop = None
        if "/serie-en-streaming/" in url or "french-anime.com" in url:
            synop = extract_series_synopsis(soup)
        else:
            synop = extract_movie_synopsis(soup)
        
        # 2. INITIALISATION DES MÉTA-DONNÉES
        year = "N/A"
        quality = "HD"
        duration = "N/A"

        # 3. LOGIQUE SPÉCIFIQUE PAR TYPE
        # Pour les ANIMES (French-Anime)
        if "french-anime.com" in url:
            info_div = soup.find('div', class_='infodesc') or soup.find('ul', class_='anime-info')
            if info_div:
                text = info_div.get_text()
                # Année
                y_match = re.search(r'Année\s*:\s*(\d{4})', text, re.I)
                year = y_match.group(1) if y_match else "N/A"
                # Type/Qualité (souvent VOSTFR ou VF)
                q_match = re.search(r'(VOSTFR|VF)', text, re.I)
                quality = q_match.group(1).upper() if q_match else "HD"
                # Durée ou Épisodes
                e_match = re.search(r'Épisodes\s*:\s*(\d+)', text, re.I)
                duration = f"{e_match.group(1)} Eps" if e_match else "N/A"

        # Pour les FILMS et SÉRIES (Flemmix)
        else:
            info_list = soup.find('ul', class_='mov-list')
            if info_list:
                text_info = info_list.get_text(separator=' ')
                # Année (recherche 4 chiffres)
                y_match = re.search(r'(19|20)\d{2}', text_info)
                if y_match: year = y_match.group(0)
                
                # Durée (ex: 1h 45min ou "22 min")
                d_match = re.search(r'(\d+h\s*\d*min?|\d+\s*min)', text_info, re.I)
                if d_match: duration = d_match.group(0)

            # Qualité (Badge sur l'image ou texte)
            q_tag = soup.find('span', class_='qlt') or soup.find('div', class_='quality')
            if q_tag: quality = q_tag.get_text(strip=True).upper()
            
            # Si c'est une série, on remplace souvent la durée par le nombre de saisons si dispo
            if "/serie-en-streaming/" in url:
                s_match = re.search(r'Saisons?\s*:\s*(\d+)', text_info, re.I)
                if s_match: duration = f"Saison {s_match.group(1)}"

        return url, {
            'plot': synop or "Synopsis non disponible.",
            'year': year,
            'quality': quality,
            'duration': duration
        }
    except:
        return url, {'plot': "Erreur de chargement.", 'year': "N/A", 'quality': "HD", 'duration': "N/A"}
# --- Interface Kodi ---
def add_item(name, action, url, thumb="", fanart="", is_folder=True, plot="", mode_type="", post_data=None):
    li = xbmcgui.ListItem(label=name)
    li.setArt({'thumb': thumb, 'icon': thumb, 'poster': thumb, 'fanart': fanart or FANART_GLOBAL})
    xbmcplugin.setContent(HANDLE, 'movies') 
    
    info = li.getVideoInfoTag()
    info.setPlot(plot or "Sélectionnez pour voir.")
    
    params = {'action': action, 'url': url, 'mode_type': mode_type}
    if post_data: 
        params['post_data'] = urllib.parse.urlencode(post_data) if isinstance(post_data, dict) else post_data
    
    xbmcplugin.addDirectoryItem(HANDLE, f"{sys.argv[0]}?{urllib.parse.urlencode(params)}", li, is_folder)

def menu_principal():
    xbmcplugin.setContent(HANDLE, 'movies')
    # Films
    add_item("🎬 FILMS", "sub_menu", "movies", 
             thumb=get_art("movie.png"), 
             mode_type="movies", 
             plot="[B][COLOR white]SECTION FILMS[/COLOR][/B]\n\nAccédez à notre catalogue complet de films classés par genres et nouveautés.")
    
    # Séries
    add_item("📺 SÉRIES", "sub_menu", "series", 
             thumb=get_art("series.png"), 
             mode_type="series", 
             plot="[B][COLOR white]SECTION SÉRIES[/COLOR][/B]\n\nRetrouvez toutes vos séries préférées, classées par saisons et épisodes.")
    
    # Animes
    add_item("㊙️ ANIMES", "sub_menu", "animes", 
             thumb=get_art("anime.png"), 
             mode_type="animes", 
             plot="[B][COLOR white]SECTION ANIMES[/COLOR][/B]\n\nDécouvrez les dernières sorties japonaises, les classiques et les simulcasts.")
    
    # Vider le cache
    add_item("[COLOR orange]🧹 VIDER LE CACHE[/COLOR]", "vider_cache", "", 
             thumb=get_art("delete.png"), 
             plot="[B][COLOR orange]MAINTENANCE[/COLOR][/B]\n\nSupprime les données temporaires et les synopsis stockés pour libérer de l'espace et actualiser les informations.")
    
    # Quitter
    add_item("[COLOR red]🚪 QUITTER[/COLOR]", "quitter", "", 
             thumb=get_art("exit.png"), 
             is_folder=False, 
             plot="[B][COLOR red]FERMER L'APPLICATION[/COLOR][/B]\n\nQuitte l'extension et retourne à l'écran d'accueil de Kodi.")
    
    xbmcplugin.endOfDirectory(HANDLE)
    force_view()

def sub_menu(mode_type):
    xbmcplugin.setContent(HANDLE, 'movies')
    add_item("[COLOR red]⬅ RETOUR[/COLOR]", "main", "", thumb=get_art("back.png"), plot="Retourner au menu principal")
    
    target = ANIME_URL if mode_type == "animes" else BASE_URL
    label = "Film" if mode_type == "movies" else "Série" if mode_type == "series" else "Anime"
    
    add_item(f"🔍 Rechercher un {label}", "search", "", thumb=get_art("search.png"), mode_type=mode_type, plot=f"Lancer une recherche de {label}s")
    
    path = "film-en-streaming" if mode_type == "movies" else "serie-en-streaming" if mode_type == "series" else "anime-en-streaming"
    add_item(f"🆕 Derniers {label}s", f"list_{mode_type}", f"{target}/{path}/", thumb=get_art("exclus.png"), mode_type=mode_type, plot=f"Voir les derniers {label}s ajoutés")
    
    if mode_type == "movies":
        add_item("⏳ Anciens", "list_movies", f"{BASE_URL}/film-ancien/", thumb=get_art("ancien.png"), mode_type="movies", plot="Archives des films anciens")
        genres_movies = [
            ("Action", "action"), ("Animation", "animation"), ("Horreur", "horreur"),
            ("Science-Fiction", "science-fiction"), ("Thriller", "thriller"), ("Western", "western"), 
            ("Arts-Martiaux", "arts-martiaux"), ("Aventure", "aventure"), ("Espionnage", "espionnage"),
            ("Comedie", "comedie"), ("Documentaire", "documentaire"), ("Guerre", "guerre"), 
            ("Historique", "historique"), ("Biopic", "biopic"), ("Policier", "policier"), 
            ("Drame", "drame"), ("Musical", "musical"), ("Romance", "romance"),  
            ("Spectacles", "spectacles"), ("Famille", "famille")
        ]
        for n, s in genres_movies:
            # On passe 'n' (le nom en majuscules ou propre) dans l'argument plot
            # Tu peux ajouter du texte comme f"Catégorie : {n}"
            add_item(n, "list_movies", f"{BASE_URL}/film-en-streaming/{s}/", thumb=get_art(s+".png"), mode_type="movies", plot=n.upper())

    elif mode_type == "animes":
        genres_animes = [
            ("Action", "action"), ("Aventure", "aventure"), ("Arts Martiaux", "arts-martiaux"),
            ("Combat", "combat"), ("Comédie", "comedie"), ("Drame", "drame"),
            ("Épouvante", "epouvante"), ("Fantastique", "fantastique"), ("Fantasy", "fantasy"),
            ("Mystère", "mystere"), ("Romance", "romance"), ("Shonen", "shonen"),
            ("Surnaturel", "surnaturel"), ("Sci-Fi", "sci-fi"), ("School Life", "school-life"),
            ("Ninja", "ninja"), ("Seinen", "seinen"), ("Horreur", "horreur"),
            ("Tranche de vie", "tranche-de-vie"), ("Psychologique", "psychologique")
        ]
        for n, s in genres_animes:
            # Idem ici, le plot affichera le nom à gauche en survol
            add_item(n, "list_animes", f"{ANIME_URL}/category/{s}/", thumb=get_art(s+".png"), mode_type="animes", plot=n.upper())

    xbmcplugin.endOfDirectory(HANDLE)
    force_view()

def search_global(m_type):
    query = xbmcgui.Dialog().input(f"Rechercher", type=xbmcgui.INPUT_ALPHANUM)
    if not query: return
    if m_type == "animes":
        data = {'do': 'search', 'subaction': 'search', 'story': query.strip(), 'search_start': '1'}
        url = f"{ANIME_URL}/index.php?do=search"
    else:
        data = {'do': 'search', 'subaction': 'search', 'story': query.strip(), 'search_start': '0', 'full_search': '0', 'result_from': '1'}
        url = f"{BASE_URL}/index.php?do=search"
    _generic_list(url, m_type, f"list_{m_type}", post_data=data)

def list_anime_episodes(url):
    r = session.get(url).text
    soup = BeautifulSoup(r, 'html.parser')
    eps_div = soup.find('div', class_='eps')
    if eps_div:
        content = eps_div.get_text(strip=True)
        parts = re.split(r'(\d+)!', content)
        found = False
        for i in range(1, len(parts), 2):
            ep_num = parts[i]; ep_urls = parts[i+1]
            if ep_urls:
                add_item(f"Épisode {ep_num}", 'select_source', ep_urls, is_folder=True, mode_type="animes")
                found = True
        if found:
            xbmcplugin.endOfDirectory(HANDLE)
            return
    select_source(url, mode_type="animes")

# --- LISTING GÉNÉRIQUE (CORRIGÉ) ---
def _generic_list(url, mode_type, action_name, post_data=None):
    xbmcplugin.setContent(HANDLE, 'movies')
    add_item("[COLOR red]⬅ RETOUR[/COLOR]", "sub_menu", "", thumb=get_art("back.png"), mode_type=mode_type)
    
    add_item("[COLOR yellow]🔢 ALLER À LA PAGE...[/COLOR]", "go_to_page", url, thumb=get_art("page.png"), mode_type=mode_type, post_data=post_data, is_folder=False)

    try:
        p_dict = {}
        if post_data:
            p_dict = dict(urllib.parse.parse_qsl(post_data)) if isinstance(post_data, str) else post_data.copy()

        r = session.post(url, data=p_dict, timeout=15) if p_dict else session.get(url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        items = soup.find_all('div', class_='mov')
        
        movies_data = []
        base_domain = ANIME_URL if mode_type == "animes" else BASE_URL
        for item in items:
            link = item.find('a', class_='mov-t')
            if not link: continue
            m_url = link['href']
            img = item.find('img')
            m_thumb = img['src'] if img else ""
            if m_thumb.startswith('/'): m_thumb = base_domain + m_thumb
            movies_data.append({'title': link.get_text(strip=True), 'url': m_url, 'thumb': m_thumb})

        # Extraction multi-threadée des synopsis et métadonnées
        to_scan = [m['url'] for m in movies_data if m['url'] not in SYNOPSIS_CACHE]
        if to_scan:
            with ThreadPoolExecutor(max_workers=10) as executor:
                for u, data in executor.map(get_single_synopsis, to_scan):
                    SYNOPSIS_CACHE[u] = data
            save_cache(SYNOPSIS_CACHE)

        # Boucle d'affichage des films/séries
        for m in movies_data:
            target = 'list_anime_episodes' if mode_type == "animes" else 'select_source'
            
            # Récupération des données (gestion de la transition ancien/nouveau cache)
            cached_info = SYNOPSIS_CACHE.get(m['url'], {})
            
            if isinstance(cached_info, dict):
                # Nouveau format avec métadonnées
                plot_text = cached_info.get('plot', "Synopsis non disponible.")
                year = cached_info.get('year', "N/A")
                quality = cached_info.get('quality', "HD")
                duration = cached_info.get('duration', "N/A")
                
                # Formatage du bloc d'information
                header = f"[B][COLOR white]{m['title'].upper()}[/COLOR][/B]"
                meta = f"[COLOR yellow]{year}[/COLOR]  |  [COLOR lime]{quality}[/COLOR]  |  [COLOR lightblue]{duration}[/COLOR]"
                full_plot = f"{header}\n{meta}\n\n{plot_text}"
            else:
                # Sécurité pour l'ancien cache (texte simple)
                full_plot = f"[B][COLOR white]{m['title']}[/COLOR][/B]\n\n{cached_info}"

            add_item(m['title'], target, m['url'], thumb=m['thumb'], plot=full_plot, mode_type=mode_type)

        # --- Gestion de la Pagination ---
        if p_dict and p_dict.get('do') == 'search':
            current_start = int(p_dict.get('search_start', 0))
            current_page = current_start + 1 if mode_type != "animes" else current_start
            page_links = soup.find_all('a', onclick=re.compile(r'list_submit', re.I))
            max_page = current_page
            for link in page_links:
                match = re.search(r'list_submit\((\d+)\)', link.get('onclick', ''), re.I)
                if match: max_page = max(max_page, int(match.group(1)))
            
            if current_page < max_page:
                next_display_page = current_page + 1
                next_start = str(next_display_page) if mode_type == "animes" else str(next_display_page - 1)
                p_dict['search_start'] = next_start
                add_item(f"[COLOR lime]➡ PAGE SUIVANTE → Page {next_display_page}[/COLOR]", action_name, url, thumb=get_art("next.png"), mode_type=mode_type, post_data=p_dict)
        else:
            pnext = soup.find('span', class_='pnext')
            next_link = pnext.find('a') if pnext else soup.find('a', string=re.compile(r'Suivant|>>', re.I))
            if next_link and next_link.get('href'):
                href = next_link['href']
                if href.startswith('/'): href = base_domain + href
                add_item("[COLOR green]➡ PAGE SUIVANTE[/COLOR]", action_name, href, thumb=get_art("next.png"), mode_type=mode_type)
                
    except Exception as e:
        xbmc.log(f"Erreur Listing Stratos: {str(e)}", xbmc.LOGERROR)
        
    xbmcplugin.endOfDirectory(HANDLE)
    force_view()
# --- SOURCES & PLAY ---
def select_source(url, mode_type=""):
    # 1. Définir le cookie de sécurité avant la requête
    session.cookies.set('h_check', '25', domain='flemmix.voto')
    
    r = session.get(url, timeout=15).text
    soup = BeautifulSoup(r, 'html.parser')
    # 1. CAS SÉRIES : Gardez votre logique existante intacte
    if "/serie-en-streaming/" in url:
        blocs = {
            "VF": soup.find('div', class_='blocfr'),
            "VOSTFR": soup.find('div', class_='blocvostfr')
        }
        found_any = False
        for lang, bloc in blocs.items():
            if bloc:
                items = bloc.find_all('li', class_='clicbtn')
                for item in items:
                    ep_name = item.get_text(strip=True)
                    rel_id = item.get('rel')
                    reader_div = soup.find('div', class_=rel_id)
                    if reader_div:
                        links = reader_div.find_all('a', onclick=re.compile(r"loadVideo"))
                        all_urls = []
                        for l in links:
                            m = re.search(r"loadVideo\(['\"]([^'\"]+)['\"]", l.get('onclick', ''))
                            if m: all_urls.append(m.group(1))
                        if all_urls:
                            add_item(f"[COLOR lime]{lang}[/COLOR] - {ep_name}", 'select_source', ",".join(all_urls), is_folder=True, mode_type="series")
                            found_any = True
        if found_any:
            xbmcplugin.endOfDirectory(HANDLE)
            return

    # 2. CAS GÉNÉRIQUE (Films ou Épisodes de séries déjà cliqués)
    if "," in url: # Si on a plusieurs sources (cas des séries traitées juste au-dessus)
        sources = url.split(',')
        for i, s in enumerate(sources, 1):
            s = s.strip()
            if not s: continue
            domain = urllib.parse.urlparse(s).netloc.replace('www.', '').split('.')[0].upper()
            li = xbmcgui.ListItem(label=f"Lecteur {i} ({domain})")
            li.setProperty('IsPlayable', 'true')
            xbmcplugin.addDirectoryItem(HANDLE, f"{sys.argv[0]}?action=play&url={s}", li, False)
    
    else:
        # 3. LOGIQUE FILM (Le bloc que vous avez ajouté)
        container = soup.find('div', class_='tabs-sel')
        if container:
            links = container.find_all('a', onclick=True)
            for link in links:
                onclick = link.get('onclick', '')
                match = re.search(r"loadVideo\(['\"](http.+?)['\"]", onclick)
                if match:
                    v_url = match.group(1)
                    label = link.get_text(strip=True)
                    li = xbmcgui.ListItem(label=f"▶ {label}")
                    li.setProperty('IsPlayable', 'true')
                    xbmcplugin.addDirectoryItem(HANDLE, f"{sys.argv[0]}?action=play&url={v_url}", li, False)
    
    xbmcplugin.endOfDirectory(HANDLE)

def verifier_licence():
    if ADDON.getSetting('stratflix_license_hash'): return True
    raw = xbmc.getInfoLabel('System.FriendlyName') + xbmc.getInfoLabel('System.KernelVersion')
    uuid = hashlib.sha256(raw.encode()).hexdigest()
    kb = xbmcgui.Dialog().input("Activation", type=xbmcgui.INPUT_ALPHANUM)
    if kb:
        try:
            res = session.post(URL_SERVEUR, data={'code': kb.upper().strip(), 'uuid': uuid}, timeout=10).json()
            if res.get('status') == "success":
                ADDON.setSetting('stratflix_license_hash', kb.upper().strip()); return True
        except: pass
    return False

if __name__ == '__main__':
    if verifier_licence():
        params = dict(urllib.parse.parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
        action = params.get('action')
        m_type = params.get('mode_type')
        u_url = params.get('url')
        p_data = params.get('post_data')
        
        if not action or action == 'main': menu_principal()
        elif action == 'sub_menu': sub_menu(m_type)
        elif action == 'quitter': quitter_addon()
        elif action == 'search': search_global(m_type)
        elif action == 'go_to_page': go_to_page(u_url, m_type, f"list_{m_type}", post_data=p_data)
        elif action == 'vider_cache': vider_cache()
        elif action == 'list_anime_episodes': list_anime_episodes(u_url)
        elif action.startswith('list_'): _generic_list(u_url, m_type, action, post_data=p_data)
        elif action == 'select_source': select_source(u_url, mode_type=m_type)
        elif action == 'play':
            try:
                import resolveurl
                path = resolveurl.resolve(u_url) or u_url
            except: path = u_url
            xbmcplugin.setResolvedUrl(HANDLE, True, xbmcgui.ListItem(path=path))
