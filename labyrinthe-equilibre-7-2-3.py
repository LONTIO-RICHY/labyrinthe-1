#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LE LABYRINTHE - version Python (Pygame)
=========================================
Reproduction fidele des mecaniques du jeu HTML original :
- labyrinthe procedural (algorithme "recursive backtracker" + raccourcis en boucle)
- camera qui suit le joueur
- monstre qui apparait a partir du niveau 3 et evolue (vitesse, intelligence, tier)
- 23 pouvoirs ramassables, geres via un inventaire (comme dans la version HTML)
- systeme de vies, de coups (deplacements) et de niveaux
- CODE DE TRICHE CREATEUR : taper L-U-K-O ou R-I-C-H-Y au clavier physique
  pendant la partie active l'usage illimite de TOUS les pouvoirs, mais
  uniquement pour le niveau en cours. Des que le niveau change, la
  capacite est perdue automatiquement (il faut retaper le code pour la
  reactiver au niveau suivant, ou au niveau ou l'on se trouve).

Installation : pip install pygame
(le module numpy est optionnel : s'il est present, les bruitages sont
synthetises comme dans la version HTML ; sinon le jeu tourne sans son)

Lancement : python labyrinthe.py

Controles :
  Fleches ou Z Q S D       -> se deplacer
  TAB                      -> changer le pouvoir selectionne dans l'inventaire
  ENTREE ou ESPACE         -> utiliser le pouvoir selectionne
  R                        -> recommencer au niveau 1
  M                        -> couper / activer le son
  P                        -> mettre en pause / reprendre (tous les minuteurs sont geles)
  F11 ou ALT+ENTREE        -> plein ecran / fenetre (la fenetre est aussi redimensionnable a la souris)
  Echap                    -> quitter le plein ecran, ou quitter le jeu si deja en fenetre
  (taper LUKO ou RICHY a la suite -> triche : pouvoirs illimites ce niveau)

VERSION EQUILIBREE (labyrinthe-equilibre.py)
---------------------------------------------
Deux changements par rapport a la version d'origine, pour lisser le pic de
difficulte qui rendait le jeu quasi injouable autour du niveau 10-14 :
  1. Maintien de touche : plus besoin de marteler les fleches, un appui
     par case. Garder une fleche enfoncee fait avancer en continu ; les
     pouvoirs de traversee/casse de mur restent reserves au premier appui.
  2. Montee en puissance du monstre ralentie apres le niveau 12 (vitesse,
     intelligence plafonnee a 88%, 2e monstre repousse au niveau 15, 3e au
     niveau 27, maximum 3 monstres au lieu de 4).
"""

import math
import os
import random
import sys
import time

import pygame

# ----------------------------------------------------------------------
# Son optionnel : on synthetise les bruitages avec numpy, comme la version
# HTML le fait avec la Web Audio API. Si numpy n'est pas installe, ou si
# le mixer audio ne demarre pas sur la machine, le jeu continue sans son
# (un message est affiche dans la console pour expliquer pourquoi).
# ----------------------------------------------------------------------
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False
    print("[son] module 'numpy' introuvable -> jeu sans son. "
          "Pour l'activer : pip install numpy")

pygame.init()

_MIXER_OK = False
try:
    pygame.mixer.init(frequency=44100, size=-16, channels=2)
    _MIXER_OK = True
except Exception as e:
    _MIXER_OK = False
    print("[son] echec de pygame.mixer.init(44100, ...) : %r" % (e,))
    # deuxieme tentative avec les reglages par defaut du systeme, au cas ou
    # la frequence/le format demande ne soit pas supporte par le pilote audio
    try:
        pygame.mixer.init()
        _MIXER_OK = True
        print("[son] reussi avec les reglages par defaut du systeme.")
    except Exception as e2:
        print("[son] echec meme avec les reglages par defaut : %r -> jeu sans son." % (e2,))

if _HAS_NUMPY and not _MIXER_OK:
    print("[son] numpy est present mais le mixer audio n'a pas pu demarrer -> jeu sans son.")

SAMPLE_RATE = 44100
if _MIXER_OK:
    _actual = pygame.mixer.get_init()
    if _actual and _actual[0]:
        SAMPLE_RATE = abs(_actual[0])
if _MIXER_OK and _HAS_NUMPY:
    print("[son] pret : mixer=%s Hz, numpy=%s" % (SAMPLE_RATE, np.__version__))
_muted = False
_in_title = True
_approach_alert_until = 0.0
APPROACH_ALERT_RADIUS = 3.5
APPROACH_ALERT_COOLDOWN = 5.0


def _to_stereo(mono):
    """Duplique un signal mono sur 2 canaux : le mixer est initialise en
    stereo (certaines machines ne restituent aucun son en mono meme si
    pygame ne signale aucune erreur)."""
    return np.column_stack([mono, mono])


def _make_tone(freq=440.0, duration=0.18, volume=0.3, wave="sine", freq_end=None):
    """Genere un pygame.mixer.Sound synthetise (equivalent des playTone() JS)."""
    if not (_HAS_NUMPY and _MIXER_OK) or _muted:
        return None
    n = max(1, int(SAMPLE_RATE * duration))
    t = np.linspace(0.0, duration, n, endpoint=False)
    if freq_end is not None and freq_end > 0:
        freqs = np.linspace(max(1.0, freq), max(1.0, freq_end), n)
        phase = 2 * math.pi * np.cumsum(freqs) / SAMPLE_RATE
    else:
        phase = 2 * math.pi * freq * t
    if wave == "square":
        arr = np.sign(np.sin(phase))
    elif wave == "sawtooth":
        arr = 2.0 * (phase / (2 * math.pi) - np.floor(0.5 + phase / (2 * math.pi)))
    elif wave == "triangle":
        arr = 2.0 * np.abs(2.0 * (phase / (2 * math.pi) - np.floor(phase / (2 * math.pi) + 0.5))) - 1.0
    else:
        arr = np.sin(phase)
    env = np.ones(n)
    attack = max(1, int(0.01 * SAMPLE_RATE))
    env[:attack] = np.linspace(0.0, 1.0, attack)
    release = max(1, int(0.06 * SAMPLE_RATE))
    if release < n:
        env[-release:] *= np.linspace(1.0, 0.0, release)
    data = (arr * env * volume * 32767).astype(np.int16)
    try:
        return pygame.sndarray.make_sound(_to_stereo(data))
    except Exception as e:
        _warn_sound_error(e)
        return None


_SOUND_ERROR_SHOWN = False


def _warn_sound_error(e):
    """Affiche l'erreur de synthese/lecture UNE SEULE FOIS dans la console
    (au lieu de l'avaler silencieusement) pour pouvoir diagnostiquer un
    probleme de compatibilite numpy/pygame sur une version recente de
    Python, sans spammer la console a chaque son rate ensuite."""
    global _SOUND_ERROR_SHOWN
    if not _SOUND_ERROR_SHOWN:
        _SOUND_ERROR_SHOWN = True
        print("[son] echec de generation/lecture d'un son : %r" % (e,))


def _play(freq=440.0, duration=0.18, volume=0.3, wave="sine", freq_end=None):
    snd = _make_tone(freq, duration, volume, wave, freq_end)
    if snd:
        snd.play()


def _noise_burst(duration=0.3, volume=0.5):
    if not (_HAS_NUMPY and _MIXER_OK) or _muted:
        return
    n = max(1, int(SAMPLE_RATE * duration))
    arr = np.random.uniform(-1, 1, n)
    env = np.linspace(1.0, 0.0, n)
    data = (arr * env * volume * 32767).astype(np.int16)
    try:
        pygame.sndarray.make_sound(_to_stereo(data)).play()
    except Exception as e:
        _warn_sound_error(e)


def _growl(freq=110.0, duration=0.5, volume=0.5, freq_end=None, tier=0):
    """Grognement/cri de creature synthetise : oscillateur grave avec
    vibrato + tremolo, melange a un souffle de bruit filtre - un rendu
    plus organique et bestial qu'un simple bip electronique, meme s'il
    reste un son genere par calcul et non un enregistrement de voix
    reelle (impossible a produire sans echantillon audio)."""
    if not (_HAS_NUMPY and _MIXER_OK) or _muted:
        return
    n = max(1, int(SAMPLE_RATE * duration))
    t = np.linspace(0.0, duration, n, endpoint=False)
    f_end = freq_end if freq_end is not None else freq * 0.6
    base_freq = np.linspace(freq, max(20.0, f_end), n)
    vibrato = 1.0 + 0.07 * np.sin(2 * math.pi * (6 + tier) * t)
    phase = 2 * math.pi * np.cumsum(base_freq * vibrato) / SAMPLE_RATE
    osc = np.sign(np.sin(phase)) * 0.55 + np.sin(phase * 0.5) * 0.45
    tremolo = 0.55 + 0.45 * np.abs(np.sin(2 * math.pi * (16 + tier * 3) * t))
    noise = np.random.uniform(-1, 1, n)
    noise = (noise + np.roll(noise, 1) + np.roll(noise, 2)) / 3.0
    arr = osc * tremolo * 0.72 + noise * 0.32
    env = np.ones(n)
    attack = max(1, int(0.02 * SAMPLE_RATE))
    env[:attack] = np.linspace(0.0, 1.0, attack)
    release = max(1, int(0.16 * SAMPLE_RATE))
    if release < n:
        env[-release:] *= np.linspace(1.0, 0.0, release)
    data = (arr * env * volume * 32767).astype(np.int16)
    try:
        pygame.sndarray.make_sound(_to_stereo(data)).play()
    except Exception as e:
        _warn_sound_error(e)


# ----------------------------------------------------------------------
# Vrais bruitages (optionnels) : si un fichier .wav/.ogg/.mp3 portant le
# bon nom est present dans le dossier "sons/" a cote de ce script, il est
# joue a la place du bruitage synthetise (qui reste le repli automatique
# si le fichier est absent, pour que le jeu marche quand meme). C'est le
# seul moyen d'avoir des sons vraiment realistes : les bruitages generes
# par calcul (sinus/carre/dents de scie) ne peuvent pas imiter une vraie
# voix ou un vrai impact enregistre - il faut de vrais enregistrements.
# Voir SOUND_FILES_README plus bas pour la liste des noms de fichiers
# attendus et ou en trouver gratuitement.
# ----------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # App transformee en .exe (PyInstaller ou equivalent) : le dossier
    # sons/ doit se trouver a cote du .exe lui-meme (sys.executable),
    # pas a cote du code source extrait temporairement.
    _APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR = os.path.join(_APP_DIR, "sons")
_SOUND_FILE_CACHE = {}


def _load_sound_file(name):
    if name in _SOUND_FILE_CACHE:
        return _SOUND_FILE_CACHE[name]
    snd = None
    if _MIXER_OK:
        for ext in (".wav", ".ogg", ".mp3"):
            path = os.path.join(SOUNDS_DIR, name + ext)
            if os.path.isfile(path):
                try:
                    snd = pygame.mixer.Sound(path)
                except Exception as e:
                    _warn_sound_error(e)
                break
    _SOUND_FILE_CACHE[name] = snd
    return snd


def _play_named(name, synth_fn):
    """Joue le vrai fichier audio 'sons/<name>.(wav|ogg|mp3)' s'il existe,
    sinon retombe sur le bruitage synthetise (synth_fn)."""
    if _muted or not _MIXER_OK:
        return
    snd = _load_sound_file(name)
    if snd is not None:
        snd.play()
    else:
        synth_fn()


def _start_background_music():
    """Lance en boucle 'sons/musique.(mp3|ogg|wav)' si le fichier existe."""
    if not _MIXER_OK:
        return
    for ext in (".mp3", ".ogg", ".wav"):
        path = os.path.join(SOUNDS_DIR, "musique" + ext)
        if os.path.isfile(path):
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.set_volume(0.0 if _muted else 0.35)
                pygame.mixer.music.play(loops=-1)
            except Exception as e:
                _warn_sound_error(e)
            return


_start_background_music()


class Sound:
    """Regroupe les effets sonores. Chaque methode cherche d'abord un vrai
    fichier audio dans sons/ (voir plus haut) et ne retombe sur le
    bruitage synthetise que s'il est absent."""

    @staticmethod
    def pickup():
        _play_named("ramasser", lambda: _play(900, 0.10, 0.18))

    @staticmethod
    def power_generic():
        _play_named("pouvoir", lambda: _play(660, 0.15, 0.20))

    @staticmethod
    def shield():
        _play_named("bouclier", lambda: _play(200, 0.12, 0.3, "square"))

    @staticmethod
    def teleport():
        _play_named("teleport", lambda: _play(1200, 0.28, 0.22, freq_end=200))

    @staticmethod
    def heal():
        def synth():
            _play(523, 0.18, 0.22)
            _play(660, 0.16, 0.2)
        _play_named("soin", synth)

    @staticmethod
    def freeze():
        _play_named("gel", lambda: _play(1400, 0.12, 0.18, "triangle"))

    @staticmethod
    def stun():
        def synth():
            _noise_burst(0.2, 0.35)
            _play(300, 0.18, 0.28, "square", freq_end=80)
        _play_named("etourdi", synth)

    @staticmethod
    def player_hit():
        def synth():
            _noise_burst(0.18, 0.4)
            _play(160, 0.22, 0.32, "sawtooth", freq_end=50)
        _play_named("joueur_touche", synth)

    @staticmethod
    def game_over():
        _play_named("defaite", lambda: _play(220, 1.0, 0.32, "sawtooth", freq_end=40))

    @staticmethod
    def victory():
        def synth():
            for i, f in enumerate([392, 494, 587, 784]):
                _play(f, 0.25, 0.22)
        _play_named("victoire", synth)

    @staticmethod
    def wall_break():
        def synth():
            _noise_burst(0.3, 0.5)
            _play(90, 0.24, 0.45, freq_end=40)
        _play_named("mur_casse", synth)

    @staticmethod
    def explosion():
        def synth():
            _noise_burst(0.45, 0.65)
            _play(140, 0.35, 0.4, "square", freq_end=30)
        _play_named("explosion", synth)

    @staticmethod
    def multi_wall_break():
        """Plusieurs murs qui cedent en meme temps (pouvoir Explosion) : on
        rejoue plusieurs fois le vrai son 'mur_casse' (ou son repli synthetise,
        avec une toute petite variation de hauteur a chaque fois) pour donner
        l'impression de plusieurs murs distincts qui explosent d'un coup,
        et non un seul."""
        for i in range(4):
            def synth(i=i):
                _noise_burst(0.26, 0.5)
                _play(90 + i * 12, 0.22, 0.4, freq_end=40 + i * 6)
            _play_named("mur_casse", synth)

    @staticmethod
    def monster_appear(tier):
        _play_named("monstre_apparait",
                     lambda: _play(90 + tier * 4, 1.2, 0.24 + tier * 0.02, freq_end=48 + tier * 3))

    @staticmethod
    def dimension():
        def synth():
            _play(680, 0.18, 0.2, "triangle", freq_end=1500)
            _play(280, 0.24, 0.16, "sine", freq_end=900)
        _play_named("dimension", synth)

    @staticmethod
    def mirror_place():
        def synth():
            _play(1000, 0.14, 0.2, "sine", freq_end=1400)
            _play(1400, 0.10, 0.14, "triangle")
        _play_named("miroir_pose", synth)

    @staticmethod
    def mirror_absorb():
        def synth():
            _play(1600, 0.20, 0.16, "sine", freq_end=2400)
            _play(900, 0.18, 0.12, "triangle", freq_end=1600)
        _play_named("miroir_absorbe", synth)

    @staticmethod
    def step(alt=False, underwater=False):
        # Toujours le vrai son de pas (pas1/pas2 fournis par l'utilisateur),
        # quel que soit le theme du niveau (pierre/plante/glace/lave/eau) :
        # avant, glace/lave/eau cherchaient un fichier dedie (pas_glace,
        # pas_lave, pas_eau) absent du dossier sons/, et retombaient sur un
        # bip synthetise.
        _play_named("pas2" if alt else "pas1",
                    lambda: _play(150 + (40 if alt else 0), 0.05, 0.10, "square", freq_end=90))

    @staticmethod
    def wall_bump():
        _play_named("mur_choc", lambda: _play(140, 0.06, 0.20, "square", freq_end=85))

    @staticmethod
    def monster_hurt(tier=0):
        _play_named("monstre_touche", lambda: _growl(160 + tier * 6, 0.28, 0.42, freq_end=70, tier=tier))

    @staticmethod
    def monster_trapped(tier=0):
        _play_named("monstre_piege", lambda: _growl(260 + tier * 10, 0.55, 0.40, freq_end=620, tier=tier))

    @staticmethod
    def monster_furious(tier=0):
        _play_named("monstre_furieux", lambda: _growl(115 + tier * 8, 0.9, 0.55, freq_end=55, tier=tier))

    @staticmethod
    def monster_approaching():
        _play_named("monstre_approche", lambda: None)

    @staticmethod
    def mirror_release():
        def synth():
            _noise_burst(0.16, 0.32)
            _play(180, 0.24, 0.32, "sawtooth", freq_end=90)
        _play_named("miroir_relache", synth)


# ----------------------------------------------------------------------
# Fenetre / apparence
# ----------------------------------------------------------------------
CELL = 60                              # taille fixe d'une case, en pixels
WALL_H = max(4, round(CELL * 0.42))    # hauteur visible des murs "3D" (face avant + face du dessus)
HUD_TOP = 236
HUD_BOTTOM = 130
SIDE_MARGIN = 24

# Toutes les valeurs ci-dessous dependent de la taille reelle de la fenetre
# et sont recalculees par recompute_layout() a chaque redimensionnement ou
# passage en plein ecran : la zone de jeu remplit alors TOUJOURS toute la
# largeur (et toute la hauteur) disponible. Plus la fenetre/l'ecran est
# grand, plus on voit de cases du labyrinthe (au lieu d'agrandir les cases
# elles-memes ou de laisser des bandes vides sur les cotes).
WIDTH = HEIGHT = GAME_W = GAME_H = FLOOR_H = GAME_X = GAME_Y = VIEW_R = 0
screen = None
HELP_BTN_RECT = None  # zone cliquable du bouton "?" (mise a jour a chaque frame)


def recompute_layout(ww, wh):
    """Recalcule la zone de jeu pour qu'elle occupe toute la fenetre (ww x wh)."""
    global WIDTH, HEIGHT, GAME_W, GAME_H, FLOOR_H, GAME_X, GAME_Y, VIEW_R, screen
    WIDTH, HEIGHT = max(360, ww), max(320, wh)
    avail_w = max(CELL * 5, WIDTH - SIDE_MARGIN * 2)
    avail_h = max(CELL * 5, HEIGHT - HUD_TOP - HUD_BOTTOM)
    cells_x = max(5, avail_w // CELL)
    if cells_x % 2 == 0:
        cells_x -= 1
    cells_y = max(5, avail_h // CELL)
    if cells_y % 2 == 0:
        cells_y -= 1
    GAME_W = int(CELL * cells_x)
    FLOOR_H = int(CELL * cells_y)
    GAME_H = FLOOR_H + WALL_H
    GAME_X = (WIDTH - GAME_W) // 2
    GAME_Y = HUD_TOP
    VIEW_R = int(max(cells_x, cells_y) // 2 + 2)
    screen = pygame.Surface((WIDTH, HEIGHT))


# taille de fenetre initiale : 85% de la resolution de l'ecran, pour que le
# jeu s'ouvre deja grand par defaut sur un PC.
try:
    _disp_info = pygame.display.Info()
    _dw, _dh = _disp_info.current_w, _disp_info.current_h
except Exception:
    _dw, _dh = 1280, 800
_is_fullscreen = False
_windowed_size = (max(900, int(_dw * 0.85)), max(650, int(_dh * 0.85)))


def _set_display_mode():
    """(Re)cree la fenetre reelle, en plein ecran ou en mode fenetre redimensionnable,
    puis recalcule la zone de jeu pour qu'elle remplisse cette nouvelle taille."""
    global window
    if _is_fullscreen:
        window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    else:
        window = pygame.display.set_mode(_windowed_size, pygame.RESIZABLE)
    recompute_layout(*window.get_size())


def toggle_fullscreen():
    global _is_fullscreen
    _is_fullscreen = not _is_fullscreen
    _set_display_mode()


def _present():
    """Affiche la surface de jeu, qui est deja a la taille exacte de la fenetre."""
    window.blit(screen, (0, 0))
    pygame.display.flip()


_set_display_mode()
pygame.display.set_caption("Le Labyrinthe")
clock = pygame.time.Clock()

FONT_TITLE = pygame.font.SysFont("segoeui,arial", 26, bold=True)
FONT_MED = pygame.font.SysFont("segoeui,arial", 18)
FONT_SMALL = pygame.font.SysFont("segoeui,arial", 14)
FONT_TINY = pygame.font.SysFont("segoeui,arial", 12, bold=True)

COL_BG_TOP = (26, 26, 46)
COL_BG_BOTTOM = (22, 33, 62)
COL_PATH_A = (176, 141, 98)
COL_PATH_B = (158, 124, 82)
COL_WALL = (74, 55, 40)
COL_WALL_EDGE = (43, 31, 22)
COL_PLAYER = (233, 69, 96)
COL_DOOR_IN = (76, 175, 80)
COL_DOOR_OUT = (255, 202, 40)
COL_TEXT = (241, 241, 241)
COL_DIM = (200, 200, 210)
COL_PANEL = (255, 255, 255)
COL_CHEAT = (255, 215, 0)

MONSTER_TIER_COLORS = [
    (110, 190, 110),
    (150, 110, 220),
    (200, 90, 90),
    (175, 60, 140),
    (60, 60, 70),
]
MONSTER_TIER_LABEL = ["LEZ", "GOB", "OGR", "DEM", "MRT"]


def lerp(a, b, t):
    return a + (b - a) * t


def _noise(x, y):
    """Bruit pseudo-aleatoire deterministe (meme formule que noise() en JS),
    utilise pour le grain de texture du sol - toujours le meme motif pour
    une case (gx, gy) donnee, sans avoir a le stocker."""
    n = math.sin(x * 127.1 + y * 311.7) * 43758.5453
    return n - math.floor(n)


def draw_vertical_gradient(surf, top_color, bottom_color):
    h = surf.get_height()
    for y in range(h):
        t = y / max(1, h - 1)
        c = (
            int(lerp(top_color[0], bottom_color[0], t)),
            int(lerp(top_color[1], bottom_color[1], t)),
            int(lerp(top_color[2], bottom_color[2], t)),
        )
        pygame.draw.line(surf, c, (0, y), (surf.get_width(), y))


# ----------------------------------------------------------------------
# Catalogue des 23 pouvoirs (identique a POWER_TYPES dans la version HTML)
# ----------------------------------------------------------------------
POWER_TYPES = [
    {"id": "superforce", "code": "SF", "name": "Super Force", "duration": 9.0,
     "color": (233, 130, 60)},
    {"id": "invisible", "code": "IN", "name": "Invisibilite", "duration": 10.0,
     "color": (180, 180, 220)},
    {"id": "permute", "code": "PM", "name": "Permutation", "duration": 0.0,
     "color": (120, 200, 220)},
    {"id": "vitesse", "code": "VT", "name": "Vitesse", "duration": 8.0,
     "color": (255, 235, 90)},
    {"id": "gel", "code": "GE", "name": "Gel du monstre", "duration": 7.0,
     "color": (140, 220, 255)},
    {"id": "vision", "code": "VI", "name": "Vision totale", "duration": 6.0,
     "color": (190, 150, 255)},
    {"id": "radar", "code": "RA", "name": "Radar de sortie", "duration": 12.0,
     "color": (255, 202, 40)},
    {"id": "bouclier", "code": "BO", "name": "Bouclier", "duration": 0.0,
     "color": (100, 170, 240)},
    {"id": "peur", "code": "PE", "name": "Peur", "duration": 8.0,
     "color": (150, 90, 200)},
    {"id": "ralenti", "code": "RL", "name": "Ralentissement", "duration": 8.0,
     "color": (150, 200, 120)},
    {"id": "leurre", "code": "LE", "name": "Leurre", "duration": 6.0,
     "color": (230, 120, 190)},
    {"id": "teleport", "code": "TP", "name": "Teleportation", "duration": 0.0,
     "color": (120, 220, 200)},
    {"id": "phase", "code": "PH", "name": "Phasage", "duration": 0.0,
     "color": (200, 200, 210)},
    {"id": "rapetisse", "code": "RP", "name": "Rapetissement", "duration": 8.0,
     "color": (200, 140, 90)},
    {"id": "dimension", "code": "DI", "name": "Autre Dimension", "duration": 10.0,
     "color": (150, 90, 230)},
    {"id": "doublepas", "code": "DP", "name": "Double Pas", "duration": 7.0,
     "color": (120, 220, 150)},
    {"id": "soin", "code": "PV", "name": "Vie Bonus", "duration": 0.0,
     "color": (233, 69, 96)},
    {"id": "confusion", "code": "CO", "name": "Confusion", "duration": 8.0,
     "color": (200, 160, 255)},
    {"id": "aimant", "code": "AI", "name": "Aimant Sortie", "duration": 10.0,
     "color": (255, 180, 60)},
    {"id": "invincible", "code": "IV", "name": "Invincibilite", "duration": 6.0,
     "color": (255, 220, 60)},
    {"id": "explosion", "code": "EX", "name": "Explosion", "duration": 0.0,
     "color": (255, 100, 60)},
    {"id": "clone", "code": "CL", "name": "Clone Leurre", "duration": 8.0,
     "color": (200, 140, 230)},
    {"id": "mirror", "code": "MR", "name": "Miroir Piegeur", "duration": 0.0,
     "color": (222, 228, 240)},
    {"id": "rembobinage", "code": "RB", "name": "Rembobinage", "duration": 0.0,
     "color": (150, 190, 255)},
    {"id": "piege_pics", "code": "PI", "name": "Piege a Pics", "duration": 0.0,
     "color": (190, 80, 70)},
    {"id": "architecte", "code": "AR", "name": "Architecte", "duration": 0.0,
     "color": (150, 120, 90)},
    {"id": "vampirisme", "code": "VA", "name": "Vampirisme", "duration": 8.0,
     "color": (170, 30, 50)},
]
POWER_BY_ID = {p["id"]: p for p in POWER_TYPES}

# Explication courte de chaque pouvoir, affichee dans le panneau d'aide
# (bouton "?" ou touche H) : une phrase suffit pour comprendre l'effet.
POWER_DESCRIPTIONS = {
    "superforce": "Tes coups deviennent surpuissants : ils maitrisent et repoussent le monstre au contact.",
    "invisible": "Tu deviens invisible : le monstre ne peut plus te reperer pendant un temps limite.",
    "permute": "Echange instantanement ta position avec celle du monstre le plus proche.",
    "vitesse": "Tu te deplaces plus vite pendant un temps limite.",
    "gel": "Gele le(s) monstre(s) sur place ; gele, un monstre se brise en un seul coup.",
    "vision": "Affiche une mini-carte du labyrinthe pendant un temps limite.",
    "radar": "Une fleche t'indique en continu la direction de la sortie.",
    "bouclier": "Absorbe une attaque de monstre sans te faire perdre de vie.",
    "peur": "Le(s) monstre(s) prennent peur et s'eloignent de toi un moment.",
    "ralenti": "Ralentit la vitesse de deplacement du (des) monstre(s).",
    "leurre": "Depose un leurre qui detourne l'attention du monstre.",
    "teleport": "Te teleporte instantanement vers un endroit aleatoire et sur du labyrinthe.",
    "phase": "Te laisse traverser un mur une seule fois, sans le detruire.",
    "rapetisse": "Retrecit le(s) monstre(s), qui deviennent plus lents et plus faibles un moment.",
    "dimension": ("Ouvre un passage vers une autre dimension pendant 10 secondes : tu ne vois plus "
                  "les monstres de ta dimension d'origine, et ton corps n'eclaire plus qu'un tout "
                  "petit rayon autour de toi, comme une mini ampoule. Tu continues pourtant a te "
                  "deplacer en meme temps dans ta dimension d'origine (chaque endroit de l'autre "
                  "dimension existe aussi chez toi), ou les monstres continuent d'agir : c'est un "
                  "moyen furtif de traverser le labyrinthe sans etre vu."),
    "doublepas": "Ton prochain deplacement te fait avancer de deux cases d'un coup.",
    "soin": "Redonne un point de vie (jusqu'a 5 vies).",
    "confusion": "Rend le(s) monstre(s) confus : ils se deplacent au hasard un moment.",
    "aimant": "Comme le radar : indique en continu la direction de la sortie, plus longtemps.",
    "invincible": "Te rend invincible aux attaques du (des) monstre(s) pendant un temps limite.",
    "explosion": "Souffle explosif : repousse et etourdit les monstres proches de toi.",
    "clone": "Cree un clone-leurre qui imite ta presence pour tromper le monstre.",
    "mirror": ("Depose un miroir juste a cote de toi. Au contact, il absorbe le monstre "
               "progressivement en emettant une lumiere blanche (2 secondes de lutte), le "
               "retient prisonnier pendant 8 secondes, puis le relache, furieux."),
    "rembobinage": "Annule ton dernier deplacement et te ramene a ta position precedente.",
    "piege_pics": "Depose un piege invisible au sol : le prochain monstre qui marche dessus est etourdi.",
    "architecte": ("Fait trembler le camp pendant 5 secondes, puis change la position de tous les murs, "
                   "en partant de la porte d'entree jusqu'a la porte de sortie."),
    "vampirisme": ("Te transforme en vampire : capuche et crocs, vapeur de sang, bords du camp teintes "
                   "de rouge. Une chauve-souris tourne autour de toi (ou fonce sur un monstre deja "
                   "proche) sans limite de temps tant qu'elle n'a mordu personne ; une fois la morsure "
                   "faite, l'effet dure encore 8 secondes avant de disparaitre, en te rendant 1 point de vie."),
}

# Stades "quasiment sombres" : le camp est plonge dans le noir, seul un tres
# petit halo de lumiere emis par le corps du joueur eclaire les environs
# immediats (indépendant du pouvoir Autre Dimension, qui a son propre halo).
DARK_LEVEL_MODULO = 3          # environ un niveau sur trois est sombre
DARK_LEVEL_MIN = 2             # jamais sombre au tout premier niveau
UNSTABLE_LEVEL_MODULO = 4      # environ un niveau sur quatre a des murs instables
UNSTABLE_LEVEL_MIN = 5          # jamais avant le niveau 5, le temps d'apprendre les bases
UNSTABLE_SECONDS_PER_STEP = 1.0    # temps de marche suppose par case du plus court chemin
UNSTABLE_EXPLORATION_FACTOR = 3.0  # marge car le joueur ne connait pas le chemin a l'avance
UNSTABLE_RESHUFFLE_MIN = 90.0      # jamais moins de 1min30, meme sur un tout petit labyrinthe
DARK_LIGHT_RADIUS_CELLS = 2.15     # portee (en cases) du faisceau de la lampe torche sur un stade sombre
DIMENSION_LIGHT_RADIUS_CELLS = 1.3  # portee (en cases), tres reduite, dans l'autre dimension

# Theme visuel des murs, tire au hasard a chaque niveau (independant du
# stade sombre) : la plupart des niveaux restent en pierre classique, mais
# certains ont des murs recouverts de plantes, de glace ou de lave/feu.
WALL_THEMES = ["pierre", "pierre", "pierre", "plante", "glace", "lave", "eau"]

MONSTER_START_LEVEL = 3
STARTING_POWER_LEVEL = 10  # a partir de ce niveau, des pouvoirs sont offerts au debut du niveau
STARTING_POWER_STEP = 10   # +1 pouvoir de depart supplementaire tous les 10 niveaux au-dela
MULTI_MONSTER_LEVEL = 15   # a partir de ce niveau, le monstre se dedouble (un deuxieme apparait)
MULTI_MONSTER_STEP = 12    # puis un monstre de plus tous les 12 niveaux au-dela (3e au niveau 27)
MAX_MONSTERS = 3           # plafond, pour que le labyrinthe reste jouable

# ----------------------------------------------------------------------
# Progression : score, defis, tresor cache, bonus de rapidite, niveaux
# boss, fil narratif et evenements rares
# ----------------------------------------------------------------------
BOSS_LEVEL_STEP = 10        # un niveau boss tous les BOSS_LEVEL_STEP niveaux
TREASURE_START_LEVEL = 2    # premier niveau ou un tresor optionnel peut apparaitre
TREASURE_CHANCE = 0.65      # probabilite qu'un tresor soit place a un niveau donne
RANDOM_EVENT_CHANCE = 0.12  # probabilite d'un coffre bonus rare par niveau
SPEED_BONUS_SECONDS = 20.0  # temps sous lequel finir un niveau rapporte un bonus
REWARD_POPUP_DURATION = 3.0  # duree d'affichage de l'animation de recompense

# Defis annonces en debut de niveau : un tire au sort a chaque niveau (a
# partir du niveau 2), change l'approche a chaque fois. "few_moves" calcule
# sa limite a partir du plus court chemin reel du niveau (voir
# pick_challenge_for_level).
CHALLENGES = [
    {"id": "no_force", "desc": "Termine le niveau sans utiliser la Super Force", "points": 40},
    {"id": "no_damage", "desc": "Termine le niveau sans perdre de vie", "points": 40},
    {"id": "few_moves", "desc": "Termine le niveau en moins de %d coups", "points": 35,
     "moves_factor": 1.7},
]

# Fil narratif leger : un message s'affiche a certains niveaux cles, pour
# devoiler peu a peu le mystere de l'autre dimension.
NARRATIVE_MESSAGES = {
    3: "Une porte s'est entrouverte quelque part... tu sens une presence etrangere.",
    6: "Des murmures venus d'ailleurs semblent guider tes pas dans le labyrinthe.",
    10: "Le voile entre les mondes s'amincit. L'autre dimension t'observe.",
    15: "Des fragments de memoire flottent autour de toi : ce labyrinthe n'est pas le premier.",
    20: "Tu commences a comprendre : chaque sortie ouvre une porte vers un monde plus etrange.",
    25: "L'autre dimension murmure ton nom. Continue, la verite approche.",
    30: "Le coeur du labyrinthe bat au rythme de l'autre monde. Tu es pres du seuil.",
}

DIR_INFO = {
    "up": (0, -1, "top", "bottom"),
    "down": (0, 1, "bottom", "top"),
    "left": (-1, 0, "left", "right"),
    "right": (1, 0, "right", "left"),
}
OPPOSITE_DIR = {"up": "down", "down": "up", "left": "right", "right": "left"}

# Pouvoir "Miroir Piegeur" : duree (en secondes) de chacune de ses phases -
# lutte/absorption progressive, retenue prisonniere, puis sortie furieuse.
MIRROR_ABSORB_DURATION = 2.0
MIRROR_HOLD_DURATION = 8.0
MIRROR_RELEASE_DURATION = 0.9

# Pouvoir "Vampirisme" : rayon (en cases) dans lequel la chauve-souris part
# aussitot pourchasser un monstre deja proche au moment de l'activation, ou
# des qu'un monstre entre dans ce rayon pendant qu'elle orbite en attendant.
# Tant qu'aucun monstre n'a ete mordu, le pouvoir reste actif sans limite de
# temps (le compte a rebours ne demarre pas encore) : la chauve-souris peut
# chercher/pourchasser aussi longtemps qu'il le faut.
VAMPIRE_BAT_CHASE_RADIUS = 4.0
VAMPIRE_BAT_FLY_SPEED = 6.0   # cases par seconde
# Duree pendant laquelle un monstre mordu se vide de son energie avant de se
# dissiper completement. C'est seulement a partir de la morsure que le
# compte a rebours du pouvoir demarre (8 secondes). Le joueur est insensible
# aux attaques des monstres tant que cette morsure est en cours (voir
# check_monster_collision).
VAMPIRE_DRAIN_DURATION = 8.0

# ----------------------------------------------------------------------
# Code de triche createur
# ----------------------------------------------------------------------
CHEAT_CODES = ["LUKO", "RICHY"]


_pause_offset = 0.0       # secondes cumulees passees en pause, retirees de time.time()
_pause_started_at = None  # instant reel (time.time()) ou la pause en cours a commence, ou None


def now():
    if _pause_started_at is not None:
        return _pause_started_at - _pause_offset  # le temps du jeu reste fige pendant la pause
    return time.time() - _pause_offset


def is_paused():
    return _pause_started_at is not None


# La pause peut venir de deux sources independantes, qui peuvent meme se
# cumuler : la pause manuelle (touche P, coupe aussi le son) et la pause
# "douce" quand on consulte le panneau des pouvoirs (S.show_help, ne coupe
# PAS le son). Tant qu'au moins une source est active, le temps du jeu
# (now()) reste fige ; il ne reprend que lorsque la derniere source active
# est retiree.
_pause_sources = set()


def _pause_add(reason):
    global _pause_started_at
    _pause_sources.add(reason)
    if _pause_started_at is None:
        _pause_started_at = time.time()


def _pause_remove(reason):
    global _pause_started_at, _pause_offset
    _pause_sources.discard(reason)
    if not _pause_sources and _pause_started_at is not None:
        _pause_offset += time.time() - _pause_started_at
        _pause_started_at = None


_pause_forced_mute = False  # True si c'est la pause manuelle qui a coupe le son (pas un choix du joueur via M)


def _set_pause_sound(paused):
    """Coupe (ou restaure) le son uniquement pour la VRAIE pause (touche P) :
    musique de fond et bruitages sont mis en silence pendant la pause
    manuelle, puis restaures exactement dans l'etat ou ils etaient juste
    avant (si le joueur avait deja coupe le son via M, il reste coupe apres
    la reprise). La pause douce du panneau des pouvoirs ne passe jamais ici."""
    global _muted, _pause_forced_mute
    if paused:
        if not _muted:
            _muted = True
            _pause_forced_mute = True
        if _MIXER_OK:
            pygame.mixer.music.set_volume(0.0)
    else:
        if _pause_forced_mute:
            _muted = False
            _pause_forced_mute = False
        if _MIXER_OK:
            pygame.mixer.music.set_volume(0.0 if _muted else 0.35)


def toggle_help():
    """Ouvre/ferme le panneau des pouvoirs : le consulter met la partie en
    pause (monstres, minuteurs... tout se fige) mais SANS couper le son,
    contrairement a la pause manuelle (touche P)."""
    if S.show_help:
        close_help()
    else:
        S.show_help = True
        _pause_add("help")


def close_help():
    if S.show_help:
        S.show_help = False
        _pause_remove("help")


def toggle_pause():
    """Met en VRAIE pause / reprend le jeu (touche P) : coupe aussi le son,
    contrairement a la pause douce du panneau des pouvoirs (voir toggle_help).
    Tous les minuteurs (pouvoirs actifs, monstre, victoire...) restent geles
    pendant toute pause, dure ou douce, car ils se basent tous sur now()."""
    if "manual" in _pause_sources:
        _pause_remove("manual")
        _set_pause_sound(False)
    else:
        _pause_add("manual")
        _set_pause_sound(True)


def reset_pause():
    global _pause_started_at, _pause_offset, _pause_forced_mute
    _pause_sources.clear()
    _pause_started_at = None
    _pause_offset = 0.0
    _pause_forced_mute = False


# ----------------------------------------------------------------------
# Etat global de la partie (equivalent des variables du closure JS)
# ----------------------------------------------------------------------
class State:
    pass


S = State()


def new_game():
    reset_pause()
    S.level = 1
    S.lives = 3
    S.moves = 0
    S.cols = 0
    S.rows = 0
    S.grid = []
    S.player = {"x": 0, "y": 0}
    S.anim = {"px": 0.0, "py": 0.0, "facing": "down", "walking": False,
              "start": 0.0, "from_x": 0, "from_y": 0, "duration": 0.16}
    S.exit = {"x": 0, "y": 0}
    S.won = False
    S.game_over = False
    S.monsters = []
    S.powers = []
    S.decoy = None
    S.mirror = None
    S.effects = {}
    S.pending_double_step = None
    S.grace_until = 0.0
    S.held_dirs = []  # touches de direction actuellement enfoncees (la derniere = celle suivie)
    S.inventory_counts = {}
    S.selected_index = 0
    S.cheat_active = False
    S.cheat_buffer = ""
    S.toast_text = ""
    S.toast_until = 0.0
    S.win_at = None
    S.msg = ""
    S.particles = []
    S.show_help = False
    S.dimension_decor = []
    S.underwater_decor = []
    S.dark_level = False
    S.unstable_level = False
    S.unstable_period = UNSTABLE_RESHUFFLE_MIN
    S.wall_theme = "pierre"
    S.gate_in_appear_at = None
    S.exit_open_at = None
    S.scorch_marks = []   # traces de brulure laissees au sol par le pouvoir Explosion
    S.fire_fx = []         # courtes animations de flammes du pouvoir Explosion
    S.vampire_bat = None   # chauve-souris du pouvoir Vampirisme

    # Progression persistante sur toute la partie (pas remise a zero a
    # chaque niveau, voir setup_level pour le reste)
    S.score = 0
    S.narrative_shown = set()
    S.pending_reward = None
    S.reward_popup = None
    S.reward_popup_until = 0.0


def effect_active(key, t):
    return S.cheat_active or t < S.effects.get(key, 0.0)


def toast(text, dur=1.5):
    S.toast_text = text
    S.toast_until = now() + dur


# ----------------------------------------------------------------------
# Particules (equivalent de spawnBurst/updateParticles/drawParticle du HTML)
# Chaque particule est definie par sa position et sa vitesse de depart ; sa
# position a un instant t est calculee analytiquement (avec gravite), ce qui
# la fige automatiquement pendant la pause puisque now() est lui-meme fige.
# ----------------------------------------------------------------------
def spawn_burst(gx, gy, count=14, colors=None, speed=2.4, life=0.5,
                 size=0.08, gravity=6.0, shape="circle"):
    colors = colors or [(255, 255, 255)]
    t0 = now()
    for _ in range(count):
        ang = random.random() * 2 * math.pi
        spd = speed * (0.35 + random.random() * 0.95)
        life_i = life * (0.55 + random.random() * 0.7)
        S.particles.append({
            "x0": gx, "y0": gy,
            "vx": math.cos(ang) * spd, "vy": math.sin(ang) * spd - speed * 0.25,
            "born": t0, "life": life_i,
            "color": random.choice(colors),
            "size": size * (0.55 + random.random() * 0.9),
            "gravity": gravity, "shape": shape,
            "rot0": random.random() * 2 * math.pi, "rot_speed": (random.random() - 0.5) * 10,
        })


def spawn_bubbles(gx, gy, count=5):
    """Petit chapelet de bulles d'air qui remontent depuis (gx, gy), emis a
    chaque pas de nage du joueur ou d'un monstre en stade immerge."""
    t0 = now()
    for _ in range(count):
        S.particles.append({
            "x0": gx + random.uniform(-0.15, 0.15), "y0": gy + random.uniform(-0.1, 0.1),
            "vx": random.uniform(-0.3, 0.3), "vy": -random.uniform(1.6, 2.6),
            "born": t0, "life": random.uniform(0.5, 0.85),
            "color": (200, 235, 255),
            "size": random.uniform(0.035, 0.08),
            "gravity": -0.6, "shape": "bulle",
            "rot0": 0.0, "rot_speed": 0.0,
        })


def particle_state(p, t):
    """Renvoie (x, y, rot, alpha) de la particule p a l'instant t."""
    e = t - p["born"]
    x = p["x0"] + p["vx"] * e
    y = p["y0"] + p["vy"] * e + 0.5 * p["gravity"] * e * e
    rot = p["rot0"] + p["rot_speed"] * e
    alpha = max(0.0, 1.0 - e / p["life"]) if p["life"] > 0 else 0.0
    return x, y, rot, alpha


def update_particles():
    t = now()
    if S.particles:
        S.particles = [p for p in S.particles if t - p["born"] < p["life"]]
    if S.scorch_marks:
        S.scorch_marks = [m for m in S.scorch_marks if t - m["born"] < 45.0]
    if S.fire_fx:
        S.fire_fx = [f for f in S.fire_fx if t - f["born"] < f["duration"]]


def draw_particle(sx, sy, p, rot, alpha):
    if alpha <= 0:
        return
    r = max(1, p["size"] * CELL)
    surf_size = int(r * 4) + 2
    surf = pygame.Surface((surf_size, surf_size), pygame.SRCALPHA)
    cx = cy = surf_size / 2
    col = (*p["color"], int(255 * alpha))
    shape = p["shape"]
    if shape == "bulle":
        pygame.draw.circle(surf, (*p["color"], int(150 * alpha)), (int(cx), int(cy)), int(r), width=1)
        pygame.draw.circle(surf, (255, 255, 255, int(120 * alpha)),
                            (int(cx - r * 0.35), int(cy - r * 0.35)), max(1, int(r * 0.3)))
    elif shape == "shard":
        pts = [(0, -r * 1.6), (r * 0.7, r * 0.6), (-r * 0.7, r * 0.6)]
        rp = [(cx + px * math.cos(rot) - py * math.sin(rot),
               cy + px * math.sin(rot) + py * math.cos(rot)) for px, py in pts]
        pygame.draw.polygon(surf, col, rp)
    elif shape == "square":
        pts = [(-r, -r), (r, -r), (r, r), (-r, r)]
        rp = [(cx + px * math.cos(rot) - py * math.sin(rot),
               cy + px * math.sin(rot) + py * math.cos(rot)) for px, py in pts]
        pygame.draw.polygon(surf, col, rp)
    else:
        pygame.draw.circle(surf, col, (int(cx), int(cy)), int(r))
    screen.blit(surf, (sx - cx, sy - cy))


# ----------------------------------------------------------------------
# Generation du labyrinthe (recursive backtracker + boucles, comme le JS)
# ----------------------------------------------------------------------
def cell():
    return {"walls": {"top": True, "right": True, "bottom": True, "left": True}}


def index(x, y):
    if x < 0 or y < 0 or x >= S.cols or y >= S.rows:
        return -1
    return x + y * S.cols


def maze_dimensions(lvl):
    size = min(6 + lvl * 2, 30)
    return size, size


def generate_maze():
    S.grid = build_maze_grid(S.cols, S.rows, S.level)


def build_maze_grid(cols, rows, level):
    """Construit une grille de labyrinthe complete et forcement solvable
    (parcours recursif + boucles), sans toucher a S.grid : utilise pour
    generer le nouveau plan du camp lors d'un remaniement des murs
    (voir start_camp_reshuffle), en plus de la generation normale d'un niveau."""
    grid = [cell() for _ in range(cols * rows)]
    visited = [False] * (cols * rows)
    stack = [0]
    visited[0] = True
    extra_loop_chance = min(0.02 * (level - 1), 0.18)

    def idx(x, y):
        if x < 0 or y < 0 or x >= cols or y >= rows:
            return -1
        return x + y * cols

    dirs = [
        (0, -1, "top", "bottom"),
        (1, 0, "right", "left"),
        (0, 1, "bottom", "top"),
        (-1, 0, "left", "right"),
    ]

    while stack:
        cur = stack[-1]
        cx, cy = cur % cols, cur // cols
        neighbors = []
        for dx, dy, wa, wb in dirs:
            ni = idx(cx + dx, cy + dy)
            if ni != -1 and not visited[ni]:
                neighbors.append((ni, wa, wb))
        if neighbors:
            ni, wa, wb = random.choice(neighbors)
            grid[cur]["walls"][wa] = False
            grid[ni]["walls"][wb] = False
            visited[ni] = True
            stack.append(ni)
        else:
            stack.pop()

    if extra_loop_chance > 0:
        loop_dirs = [(1, 0, "right", "left"), (0, 1, "bottom", "top")]
        for y in range(rows):
            for x in range(cols):
                if random.random() < extra_loop_chance:
                    dx, dy, wa, wb = random.choice(loop_dirs)
                    ni = idx(x + dx, y + dy)
                    if ni != -1:
                        grid[idx(x, y)]["walls"][wa] = False
                        grid[ni]["walls"][wb] = False
    return grid


# ----------------------------------------------------------------------
# Remaniement du camp : le pouvoir Architecte change la position de tous
# les murs du labyrinthe. Deroulement en deux temps, pour que ce soit
# lisible et "realiste" plutot qu'un changement brutal instantane :
#   1. TREMBLEMENT (5 secondes) : le camp tremble, avertit le joueur.
#   2. BALAYAGE (3 secondes) : les murs se reconstruisent case par case,
#      en partant d'une porte vers l'autre (entree -> sortie pour le
#      pouvoir, sortie -> entree pour le declenchement automatique par
#      inactivite), avec une petite explosion de particules a chaque
#      case qui se transforme.
# Le nouveau plan est toujours entierement genere par build_maze_grid,
# donc toujours solvable, quelle que soit la position du joueur.
# Les monstres n'ont besoin d'aucun code special pour s'adapter : leur
# IA (step_toward_bfs / bfs_distances) relit S.grid en direct a chaque
# decision, murs casses ou remanies compris.
# ----------------------------------------------------------------------
CAMP_SHAKE_DURATION = 5.0
CAMP_SWEEP_DURATION = 3.0
_WALL_OPPOSITE = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}
_WALL_NEIGHBOR_DELTA = {"top": (0, -1), "bottom": (0, 1), "left": (-1, 0), "right": (1, 0)}
IDLE_RESHUFFLE_BASE = 360.0    # 6 minutes d'inactivite avant le 1er declenchement automatique
IDLE_RESHUFFLE_MIN = 90.0      # ne descend jamais en dessous de 1min30 entre deux declenchements
IDLE_RESHUFFLE_FACTOR = 0.7    # chaque declenchement raccourcit le suivant (ca se repete plus souvent)


def rebalance_moves_challenge(t):
    """Le defi 'peu de coups' calcule sa limite une seule fois, au debut du
    niveau, a partir du plus court chemin de CE moment-la. Si le camp se
    remanie en cours de route (pouvoir Architecte, inactivite ou niveau
    instable), ce plus court chemin change : on recalcule alors la limite
    a partir de la position actuelle du joueur, en gardant les coups deja
    faits, pour que le defi reste juste (ni impossible, ni trivial) plutot
    que fige sur un labyrinthe qui n'existe plus."""
    c = S.challenge
    if not c or c["id"] != "few_moves" or c.get("broken"):
        return
    shortest_now = bfs_distances(index(S.player["x"], S.player["y"]))[index(S.exit["x"], S.exit["y"])]
    if shortest_now < 0:
        return  # ne devrait jamais arriver (le nouveau plan est toujours connexe), securite
    remaining = max(6, int(shortest_now * c["moves_factor"]))
    c["limit"] = S.moves + remaining
    c["desc"] = "Termine le niveau en moins de %d coups" % c["limit"]


def start_camp_reshuffle(direction, source="power"):
    """direction: 'entree_vers_sortie' ou 'sortie_vers_entree'.
    source: 'power' (pouvoir Architecte), 'idle' (le joueur traine trop
    sans atteindre la sortie) ou 'unstable' (niveau a murs instables,
    remaniement automatique toutes les UNSTABLE_RESHUFFLE_PERIOD secondes)."""
    if S.reshuffle and S.reshuffle.get("phase") != "done":
        return False  # deja en cours, on ne relance pas par-dessus
    t = now()
    S.reshuffle = {"phase": "tremble", "start": t, "direction": direction, "source": source}
    trigger_shake(9, CAMP_SHAKE_DURATION)
    Sound.wall_bump()
    if source == "idle":
        toast("Tu traines trop pres de la sortie... le camp s'impatiente et se met a trembler !")
    elif source == "unstable":
        toast("Ce camp est instable : les murs se remettent a trembler...")
    else:
        toast("Tu invoques l'Architecte : le camp se met a trembler...")
    return True


def update_camp_reshuffle(t):
    r = S.reshuffle
    if not r or r["phase"] == "done":
        return

    if r["phase"] == "tremble":
        if t - r["start"] >= CAMP_SHAKE_DURATION:
            new_grid = build_maze_grid(S.cols, S.rows, S.level)
            origin = (S.exit["x"], S.exit["y"]) if r["direction"] == "sortie_vers_entree" else (0, 0)
            order = sorted(range(S.cols * S.rows),
                            key=lambda i: abs(i % S.cols - origin[0]) + abs(i // S.cols - origin[1]))
            max_d = max(1, abs(order[-1] % S.cols - origin[0]) + abs(order[-1] // S.cols - origin[1]))
            r["new_grid"] = new_grid
            r["schedule"] = [(i, (abs(i % S.cols - origin[0]) + abs(i // S.cols - origin[1])) / max_d
                               * CAMP_SWEEP_DURATION) for i in order]
            r["next_idx"] = 0
            r["sweep_start"] = t
            r["phase"] = "sweep"
            toast("Les murs du camp commencent a changer de position...")
        return

    if r["phase"] == "sweep":
        elapsed = t - r["sweep_start"]
        schedule = r["schedule"]
        i = r["next_idx"]
        applied_any = False
        while i < len(schedule) and schedule[i][1] <= elapsed:
            cell_idx, _ = schedule[i]
            cx, cy = cell_idx % S.cols, cell_idx // S.cols
            new_walls = r["new_grid"][cell_idx]["walls"]
            S.grid[cell_idx]["walls"] = dict(new_walls)
            # Synchronise tout de suite le mur partage avec chaque voisin
            # deja present dans la grille, pour que les deux cotes d'un
            # meme mur soient toujours d'accord (jamais l'un ouvert et
            # l'autre encore ferme, meme une fraction de seconde) : le
            # voisin recevra de toute facon exactement la meme valeur
            # quand son propre tour viendra, donc rien n'est perdu.
            for wall_name, (wdx, wdy) in _WALL_NEIGHBOR_DELTA.items():
                ni = index(cx + wdx, cy + wdy)
                if ni != -1:
                    S.grid[ni]["walls"][_WALL_OPPOSITE[wall_name]] = new_walls[wall_name]
            spawn_burst(cx, cy, count=6, colors=[(150, 120, 90), (110, 85, 60), (200, 190, 170)],
                        speed=1.6, life=0.35, size=0.06, gravity=6, shape="square")
            applied_any = True
            i += 1
        r["next_idx"] = i
        if applied_any and random.random() < 0.5:
            Sound.wall_break()
        if i >= len(schedule):
            r["phase"] = "done"
            t_done = t
            S.last_move_time = t_done         # on relance le decompte d'inactivite a zero
            S.last_unstable_reshuffle_at = t_done  # ... et celui du prochain remaniement periodique
            rebalance_moves_challenge(t_done)  # le defi "peu de coups" suit le nouveau plan du camp
            toast("Le camp a fini de se transformer !")


def check_idle_reshuffle(t):
    if S.game_over or S.won:
        return
    if S.reshuffle and S.reshuffle.get("phase") != "done":
        return
    threshold = max(IDLE_RESHUFFLE_MIN, IDLE_RESHUFFLE_BASE * (IDLE_RESHUFFLE_FACTOR ** S.idle_reshuffle_count))
    if t - S.last_move_time >= threshold:
        S.idle_reshuffle_count += 1
        start_camp_reshuffle("sortie_vers_entree", source="idle")


def check_unstable_reshuffle(t):
    """Sur un niveau instable (S.unstable_level), tous les murs changent
    de position automatiquement toutes les UNSTABLE_RESHUFFLE_PERIOD
    secondes (60s par defaut), que le joueur bouge ou non - le meme
    scenario (tremblement puis balayage) se reproduit en boucle."""
    if not S.unstable_level or S.game_over or S.won:
        return
    if S.reshuffle and S.reshuffle.get("phase") != "done":
        return
    if t - S.last_unstable_reshuffle_at >= S.unstable_period:
        direction = random.choice(["entree_vers_sortie", "sortie_vers_entree"])
        start_camp_reshuffle(direction, source="unstable")


# ----------------------------------------------------------------------
# Utilitaires BFS (identiques a la logique JS)
# ----------------------------------------------------------------------
def bfs_distances(start_idx):
    dist = [-1] * (S.cols * S.rows)
    dist[start_idx] = 0
    queue = [start_idx]
    qi = 0
    while qi < len(queue):
        cur = queue[qi]
        qi += 1
        cx, cy = cur % S.cols, cur // S.cols
        c = S.grid[cur]
        nbrs = []
        if not c["walls"]["top"]:
            nbrs.append(index(cx, cy - 1))
        if not c["walls"]["bottom"]:
            nbrs.append(index(cx, cy + 1))
        if not c["walls"]["left"]:
            nbrs.append(index(cx - 1, cy))
        if not c["walls"]["right"]:
            nbrs.append(index(cx + 1, cy))
        for n in nbrs:
            if n != -1 and dist[n] == -1:
                dist[n] = dist[cur] + 1
                queue.append(n)
    return dist


def open_neighbors(x, y):
    c = S.grid[index(x, y)]
    nbrs = []
    if not c["walls"]["top"]:
        nbrs.append((x, y - 1))
    if not c["walls"]["bottom"]:
        nbrs.append((x, y + 1))
    if not c["walls"]["left"]:
        nbrs.append((x - 1, y))
    if not c["walls"]["right"]:
        nbrs.append((x + 1, y))
    return nbrs


def step_toward_bfs(mx, my, tx, ty):
    dist = bfs_distances(index(tx, ty))
    nbrs = open_neighbors(mx, my)
    best, best_d = None, float("inf")
    for nx, ny in nbrs:
        d = dist[index(nx, ny)]
        if d != -1 and d < best_d:
            best_d = d
            best = (nx, ny)
    return best


def flee_neighbor_cell(mx, my, px, py):
    nbrs = open_neighbors(mx, my)
    if not nbrs:
        return None
    best, best_d = nbrs[0], -1
    for nx, ny in nbrs:
        d = abs(nx - px) + abs(ny - py)
        if d > best_d:
            best_d = d
            best = (nx, ny)
    return best


def random_neighbor_cell(x, y, avoid):
    nbrs = open_neighbors(x, y)
    if not nbrs:
        return None
    options = nbrs
    if avoid and len(nbrs) > 1:
        filtered = [n for n in nbrs if n != avoid]
        if filtered:
            options = filtered
    return random.choice(options)


def pick_monster_spawn():
    d = bfs_distances(index(0, 0))
    best_idx, best_d = 0, -1
    for i, v in enumerate(d):
        if v > best_d:
            best_d = v
            best_idx = i
    return best_idx % S.cols, best_idx // S.cols


def random_open_cell(exclude_list):
    tries = 0
    c = (0, 0)
    while True:
        c = (random.randrange(S.cols), random.randrange(S.rows))
        tries += 1
        if tries >= 60 or not exclude_list or c not in exclude_list:
            break
    return c


def can_move_dir(x, y, direction):
    c = S.grid[index(x, y)]
    _, _, wall_a, _ = DIR_INFO[direction]
    return not c["walls"][wall_a]


def break_wall(x, y, direction):
    dx, dy, wall_a, wall_b = DIR_INFO[direction]
    ni = index(x + dx, y + dy)
    if ni == -1:
        return False
    S.grid[index(x, y)]["walls"][wall_a] = False
    S.grid[ni]["walls"][wall_b] = False
    return True


def explode_around(x, y):
    for d in ("up", "down", "left", "right"):
        break_wall(x, y, d)


def spawn_explosion_fx(gx, gy):
    """Ajoute, a l'endroit d'une explosion (pouvoir Explosion) : une trace de
    brulure qui reste au sol un bon moment (s'estompe lentement), et une
    courte animation de flammes qui jaillissent puis s'eteignent."""
    t0 = now()
    S.scorch_marks.append({"x": gx, "y": gy, "born": t0})
    S.fire_fx.append({"x": gx, "y": gy, "born": t0, "duration": 1.0})


def build_wall(x, y, direction, t, duration=6.0):
    """Pouvoir Architecte : erige un mur temporaire (inverse de break_wall),
    restaure automatiquement par update_temp_walls apres 'duration' secondes."""
    dx, dy, wall_a, wall_b = DIR_INFO[direction]
    ni = index(x + dx, y + dy)
    if ni == -1:
        return False
    S.grid[index(x, y)]["walls"][wall_a] = True
    S.grid[ni]["walls"][wall_b] = True
    S.temp_walls.append({"x": x, "y": y, "direction": direction, "until": t + duration})
    return True


def update_temp_walls(t):
    remaining = []
    for w in S.temp_walls:
        if t >= w["until"]:
            break_wall(w["x"], w["y"], w["direction"])
        else:
            remaining.append(w)
    S.temp_walls = remaining


# ----------------------------------------------------------------------
# Monstre : stats par niveau, choix des pouvoirs (identique a la logique JS)
# ----------------------------------------------------------------------
def power_duration_multiplier(lvl):
    """Les pouvoirs a duree (Super Force, Invisibilite, Gel, Peur, ...)
    durent de plus en plus longtemps avec le niveau : +3% par niveau,
    plafonne a +60% (niveau 20 et au-dela)."""
    return 1.0 + min(0.60, (lvl - 1) * 0.03)


def player_force_power(lvl):
    """Puissance d'un coup de Super Force : au niveau 1 il faut le nombre
    de coups habituel (force_hits_needed du monstre) ; avec le niveau,
    chaque coup compte pour plus d'un, donc il en faut de moins en moins,
    ce qui contrebalance la resistance croissante du monstre."""
    return 1 + min(3, (lvl - 1) // 8)


def player_base_step_duration(lvl):
    """Vitesse de deplacement de base du joueur (secondes par case) :
    0.16s au niveau 1, de plus en plus rapide, jusqu'a un plancher de
    0.11s (niveau 26 et au-dela) - le joueur reste toujours legerement
    plus rapide que le monstre le plus rapide (plancher 0.26s)."""
    return max(0.11, 0.16 - (lvl - 1) * 0.002)


def monster_stats_for_level(lvl):
    if lvl < MONSTER_START_LEVEL:
        return None
    since = lvl - MONSTER_START_LEVEL
    # Vitesse du monstre : progression regulliere jusqu'au niveau 13
    # (0,95s au niveau 3 -> 0,36s au niveau 13), puis la montee en
    # puissance ralentit nettement pour ne pas depasser le joueur, qui
    # avance toujours a 0,16s par pas (0,1s avec le pouvoir Vitesse).
    if since <= 10:  # jusqu'au niveau 13 inclus
        base_speed = 0.95 - since * 0.059
    else:
        base_speed = max(0.26, 0.36 - (since - 10) * 0.01)
    smarts = min(0.88, 0.12 + since * 0.11)
    tier = min(4, since)
    # Comme dans la version HTML : le monstre grossit visuellement, resiste de
    # plus en plus a la Super Force (il faut plusieurs coups), et le Gel dure
    # de moins en moins longtemps sur lui a mesure qu'il devient plus fort.
    size_mult = min(2.3, 1 + since * 0.16)
    force_hits_needed = min(8, 1 + since)
    freeze_resist = min(0.85, since * 0.15)
    return {"base_speed": base_speed, "smarts": smarts, "tier": tier, "since": since,
            "size_mult": size_mult, "force_hits_needed": force_hits_needed,
            "freeze_resist": freeze_resist}


def monster_count_for_level(lvl):
    """Combien de monstres presents a ce niveau : un seul jusqu'a
    MULTI_MONSTER_LEVEL, puis il se dedouble et se rededouble regulierement,
    jusqu'a un plafond pour rester jouable."""
    if lvl < MONSTER_START_LEVEL:
        return 0
    if lvl < MULTI_MONSTER_LEVEL:
        return 1
    return min(MAX_MONSTERS, 2 + (lvl - MULTI_MONSTER_LEVEL) // MULTI_MONSTER_STEP)


def starting_powers_for_level(lvl):
    """Combien de pouvoirs sont deja dans l'inventaire au debut du niveau :
    0 avant STARTING_POWER_LEVEL, puis 1, et un de plus tous les
    STARTING_POWER_STEP niveaux, pour suivre la difficulte croissante."""
    if lvl < STARTING_POWER_LEVEL:
        return 0
    return 1 + (lvl - STARTING_POWER_LEVEL) // STARTING_POWER_STEP


def pick_monster_spawns(count):
    """Choisit jusqu'a 'count' cases distinctes, le plus loin possible du
    depart (0,0), pour placer plusieurs monstres sans qu'ils se superposent."""
    if count <= 0:
        return []
    d = bfs_distances(index(0, 0))
    order = sorted(range(len(d)), key=lambda i: -d[i])
    spawns = []
    for idx in order:
        c = (idx % S.cols, idx // S.cols)
        if c not in spawns:
            spawns.append(c)
        if len(spawns) >= count:
            break
    return spawns



def powers_count_for_level(lvl):
    # Plus le niveau augmente, plus il y a de pouvoirs disposes sur le
    # terrain : on ne plafonne plus a 6, la difficulte croissante est
    # recompensee par de plus en plus de ressources (jusqu'au maximum de
    # pouvoirs differents qui existent dans le jeu).
    return max(0, min(len(POWER_TYPES), lvl - 1))


def pick_powers_for_level(lvl, monster_spawns):
    n = powers_count_for_level(lvl)
    pool = POWER_TYPES[:]
    random.shuffle(pool)
    chosen = pool[:n]
    used = [(0, 0), (S.exit["x"], S.exit["y"])]
    if monster_spawns:
        used.extend(monster_spawns)
    result = []
    for d in chosen:
        tries = 0
        c = (0, 0)
        while True:
            c = (random.randrange(S.cols), random.randrange(S.rows))
            tries += 1
            if tries >= 60 or (c not in used and c not in [(r["x"], r["y"]) for r in result]):
                break
        result.append({"x": c[0], "y": c[1], "def": d})
    return result


# ----------------------------------------------------------------------
# Mise en place d'un niveau
# ----------------------------------------------------------------------
def setup_level():
    S.won = False
    S.game_over = False
    S.moves = 0
    S.msg = ""
    S.effects = {}
    S.decoy = None
    S.spike_trap = None
    S.temp_walls = []
    S.scorch_marks = []
    S.fire_fx = []
    S.vampire_bat = None
    S.prev_pos = None
    S.player_trail = []
    S.mirror = None
    S.pending_double_step = None
    S.grace_until = 0.0
    S.cheat_active = False
    S.cheat_buffer = ""
    S.win_at = None
    S.inventory_counts = {}
    S.selected_index = 0
    S.particles = []
    S.reshuffle = None
    S.last_move_time = now()
    S.idle_reshuffle_count = 0

    # Progression propre a ce niveau (le defi, qui a besoin du plus court
    # chemin reel, est calcule plus bas une fois le labyrinthe genere)
    S.level_start_time = now()
    S.is_boss_level = (S.level % BOSS_LEVEL_STEP == 0)
    S.challenge = None
    S.treasure = None
    S.treasure_found = False
    S.bonus_chest = None
    S.bonus_chest_found = False

    S.monsters = []

    S.cols, S.rows = maze_dimensions(S.level)
    generate_maze()

    S.dark_level = S.level >= DARK_LEVEL_MIN and (S.level % DARK_LEVEL_MODULO == 0)
    S.unstable_level = S.level >= UNSTABLE_LEVEL_MIN and (S.level % UNSTABLE_LEVEL_MODULO == 0)
    S.last_unstable_reshuffle_at = now()
    # le niveau 1 reste en pierre classique, pour poser le style du jeu
    # avant d'introduire les variantes ; ensuite le theme est tire au hasard
    # a chaque nouveau niveau.
    S.wall_theme = "pierre" if S.level <= 1 else random.choice(WALL_THEMES)

    S.player = {"x": 0, "y": 0}
    S.exit = {"x": S.cols - 1, "y": S.rows - 1}
    # Periode avant remaniement automatique (niveaux instables) : basee sur
    # le vrai plus court chemin de CE labyrinthe (calcule juste apres sa
    # generation), avec une marge d'exploration genereuse - jamais une
    # duree fixe, pour ne jamais tomber plus courte que le temps qu'il
    # faut, au minimum, pour esperer atteindre la sortie une premiere fois.
    _shortest = bfs_distances(index(0, 0))[index(S.exit["x"], S.exit["y"])]
    S.unstable_period = max(UNSTABLE_RESHUFFLE_MIN,
                             max(1, _shortest) * UNSTABLE_SECONDS_PER_STEP * UNSTABLE_EXPLORATION_FACTOR)
    S.dimension_decor = generate_dimension_decor()
    S.underwater_decor = generate_underwater_decor() if S.wall_theme == "eau" else []
    S.anim = {"px": 0.0, "py": 0.0, "facing": "down", "walking": False,
              "start": 0.0, "from_x": 0, "from_y": 0, "duration": 0.16}

    # porte d'entree : elle vient d'apparaitre, s'ouvre pour laisser sortir
    # le joueur du camp, puis se referme et disparait toute seule apres
    # quelques secondes (voir compute_gate_anim). La porte de sortie, elle,
    # reste fermee jusqu'a ce que le joueur l'atteigne (voir update_player_anim).
    S.gate_in_appear_at = now()
    S.exit_open_at = None

    mstats = monster_stats_for_level(S.level)
    if mstats:
        count = monster_count_for_level(S.level)
        for sx, sy in pick_monster_spawns(count):
            S.monsters.append({
                "x": sx, "y": sy,
                "base_speed": mstats["base_speed"], "smarts": mstats["smarts"], "tier": mstats["tier"],
                "since": mstats["since"], "size_mult": mstats["size_mult"],
                "force_hits_needed": mstats["force_hits_needed"], "freeze_resist": mstats["freeze_resist"],
                "force_hits_taken": 0,
                "next_move_at": now() + mstats["base_speed"],
                "frozen_until": 0.0, "fear_until": 0.0, "slow_until": 0.0,
                "shrunk_until": 0.0, "confused_until": 0.0, "last_cell": None,
                "anim": {"px": float(sx), "py": float(sy), "from_x": sx, "from_y": sy,
                         "walking": False, "start": 0.0, "duration": 0.22},
            })
        Sound.monster_appear(mstats["tier"])

    # Niveau boss : un monstre unique et bien plus impressionnant que la
    # simple progression statistique habituelle (plus gros, plus coriace,
    # plus rapide), pour marquer le coup visuellement tous les
    # BOSS_LEVEL_STEP niveaux.
    if S.is_boss_level and S.monsters:
        boss = S.monsters[0]
        boss["boss"] = True
        boss["size_mult"] = min(3.4, boss["size_mult"] * 1.6)
        boss["force_hits_needed"] = boss["force_hits_needed"] + 2
        boss["base_speed"] = max(0.16, boss["base_speed"] * 0.85)
        boss["freeze_resist"] = min(0.92, boss["freeze_resist"] + 0.15)

    S.powers = pick_powers_for_level(S.level, [(m["x"], m["y"]) for m in S.monsters])

    # Objectif secondaire optionnel (tresor) et evenement rare (coffre bonus)
    place_treasure()
    place_bonus_chest()

    # Defi annonce en debut de niveau : a besoin du labyrinthe et de la
    # sortie deja en place pour calculer sa limite eventuelle.
    S.challenge = pick_challenge_for_level(S.level)

    # A partir d'un certain niveau, le jeu devient plus difficile : pour
    # compenser, le joueur arrive directement sur le terrain avec un ou
    # plusieurs pouvoirs deja en reserve dans son inventaire (tires au
    # hasard), au lieu de devoir d'abord en trouver un. Ce nombre augmente
    # lui aussi progressivement avec le niveau.
    n_starters = starting_powers_for_level(S.level)
    if n_starters > 0:
        names = []
        for _ in range(n_starters):
            starter = random.choice(POWER_TYPES)
            S.inventory_counts[starter["id"]] = S.inventory_counts.get(starter["id"], 0) + 1
            names.append(starter["name"])
        S.selected_index = 0
        toast("Niveau difficile : %s offert(s) au depart !" % ", ".join(names))
    elif S.dark_level:
        toast("Stade plonge dans le noir... seul un halo de lumiere t'entoure.", dur=2.4)
    elif S.wall_theme == "plante":
        toast("Ce stade est envahi par la vegetation...", dur=2.2)
    elif S.wall_theme == "glace":
        toast("Ce stade est entierement gele...", dur=2.2)
    elif S.wall_theme == "lave":
        toast("Attention, ce stade baigne dans la lave en fusion...", dur=2.2)
    elif S.wall_theme == "eau":
        toast("Stade immerge : il faut nager pour avancer, prudence...", dur=2.2)

    # Ces messages sont volontairement affiches apres ceux ci-dessus : ils
    # se remplacent l'un l'autre dans le meme bandeau (un seul toast a la
    # fois), du moins important au plus important, pour que le defi puis,
    # plus rarement, le fil narratif ou l'alerte de niveau boss restent
    # visibles en dernier.
    if S.challenge:
        toast("Defi du niveau : %s (recompense bonus si reussi)" % S.challenge["desc"], dur=2.8)

    narrative = NARRATIVE_MESSAGES.get(S.level)
    if narrative and S.level not in S.narrative_shown:
        S.narrative_shown.add(S.level)
        toast(narrative, dur=3.4)

    if S.is_boss_level:
        toast("NIVEAU BOSS : un monstre unique et redoutable rode ici !", dur=3.0)


def find_dead_end_cells(exclude):
    """Renvoie les cases 'impasses' (un seul passage ouvert), hors des cases
    a exclure : ideales pour cacher un tresor ou un coffre bonus a l'ecart
    du chemin direct vers la sortie."""
    cells = []
    for gy in range(S.rows):
        for gx in range(S.cols):
            if (gx, gy) in exclude:
                continue
            if len(open_neighbors(gx, gy)) == 1:
                cells.append((gx, gy))
    return cells


def place_treasure():
    """Objectif secondaire optionnel : un tresor cache dans une impasse du
    labyrinthe, a partir de TREASURE_START_LEVEL. Rien n'oblige a le
    trouver pour finir le niveau, mais il rapporte des points bonus."""
    S.treasure = None
    if S.level < TREASURE_START_LEVEL or random.random() > TREASURE_CHANCE:
        return
    used = {(0, 0), (S.exit["x"], S.exit["y"])}
    used.update((m["x"], m["y"]) for m in S.monsters)
    used.update((p["x"], p["y"]) for p in S.powers)
    candidates = find_dead_end_cells(used)
    if not candidates:
        return
    tx, ty = random.choice(candidates)
    S.treasure = {"x": tx, "y": ty}


def place_bonus_chest():
    """Evenement aleatoire rare : un coffre bonus qui n'apparait
    qu'occasionnellement, cache dans une impasse differente de celle du
    tresor, pour casser la routine. Donne des points et un pouvoir
    aleatoire des qu'il est ramasse."""
    S.bonus_chest = None
    if random.random() > RANDOM_EVENT_CHANCE:
        return
    used = {(0, 0), (S.exit["x"], S.exit["y"])}
    used.update((m["x"], m["y"]) for m in S.monsters)
    used.update((p["x"], p["y"]) for p in S.powers)
    if S.treasure:
        used.add((S.treasure["x"], S.treasure["y"]))
    candidates = find_dead_end_cells(used)
    if not candidates:
        return
    cx, cy = random.choice(candidates)
    S.bonus_chest = {"x": cx, "y": cy}


def pick_challenge_for_level(lvl):
    """Choisit un defi annonce en debut de niveau, tire au sort parmi
    CHALLENGES a partir du niveau 2 (le niveau 1 sert d'introduction
    tranquille) : l'approche demandee change ainsi a chaque niveau."""
    if lvl < 2:
        return None
    kind = random.choice(CHALLENGES)
    if kind["id"] == "few_moves":
        dist = bfs_distances(index(0, 0))
        shortest = dist[index(S.exit["x"], S.exit["y"])]
        if shortest <= 0:
            return None
        limit = max(6, int(shortest * kind["moves_factor"]))
        return {"id": "few_moves", "desc": kind["desc"] % limit, "points": kind["points"],
                "limit": limit, "moves_factor": kind["moves_factor"], "broken": False}
    return {"id": kind["id"], "desc": kind["desc"], "points": kind["points"], "broken": False}


def challenge_still_valid():
    """Vrai si le defi du niveau en cours n'a pas encore ete rate."""
    c = S.challenge
    if not c or c.get("broken"):
        return False
    if c["id"] == "few_moves" and S.moves > c["limit"]:
        c["broken"] = True
        return False
    return True


def finish_level_rewards(t):
    """Calcule les points gagnes en terminant le niveau (base + bonus de
    rapidite + defi reussi + tresor trouve + coffre bonus + niveau boss) et
    prepare la recompense (un pouvoir tire au sort) qui sera donnee au
    joueur pour l'aider au niveau suivant. Une petite animation la
    presente juste apres le changement de niveau (voir draw_reward_popup)."""
    breakdown = []
    base = 100 + S.level * 5
    total = base
    breakdown.append(("Niveau termine", base))

    if (t - S.level_start_time) <= SPEED_BONUS_SECONDS:
        bonus = 30
        total += bonus
        breakdown.append(("Bonus de rapidite", bonus))

    if S.challenge and challenge_still_valid():
        bonus = S.challenge["points"]
        total += bonus
        breakdown.append(("Defi reussi", bonus))

    if S.treasure_found:
        bonus = 50
        total += bonus
        breakdown.append(("Tresor secret trouve", bonus))

    if S.bonus_chest_found:
        bonus = 70
        total += bonus
        breakdown.append(("Coffre mysterieux", bonus))

    if S.is_boss_level:
        bonus = 150
        total += bonus
        breakdown.append(("Niveau boss vaincu", bonus))

    S.score += total
    reward_power = random.choice(POWER_TYPES)
    S.pending_reward = {"points": total, "breakdown": breakdown, "power": reward_power}


def _generate_glow_decor(kinds, palette, n_max=40, n_div=5):
    """Peuple discretement le labyrinthe de petites creatures/plantes
    inoffensives et lumineuses. Base commune reutilisee par l'autre
    dimension et le monde aquatique, qui ont chacun leur propre bestiaire
    et palette mais le meme comportement (scintillement, halo)."""
    decor = []
    n = min(n_max, max(8, (S.cols * S.rows) // n_div))
    forbidden = {(0, 0), (S.exit["x"], S.exit["y"])}
    for _ in range(n):
        gx = random.randint(0, S.cols - 1)
        gy = random.randint(0, S.rows - 1)
        if (gx, gy) in forbidden:
            continue
        decor.append({
            "x": gx + random.uniform(-0.25, 0.25),
            "y": gy + random.uniform(-0.25, 0.25),
            "kind": random.choice(kinds),
            "color": random.choice(palette),
            "size": random.uniform(0.10, 0.16),
            "phase": random.uniform(0, math.tau),
        })
    return decor


def generate_dimension_decor():
    """Peuple l'autre dimension de vegetation et de vie lumineuses : lianes
    et feuilles colorees posees au sol, et petites creatures - certaines
    fixes, d'autres qui se deplacent lentement en boucle, d'autres encore
    qui grignotent une feuille juste a cote d'elles."""
    decor = []
    n = min(70, max(14, (S.cols * S.rows) // 3))
    palette = [(255, 120, 200), (140, 255, 210), (150, 190, 255), (255, 210, 120),
               (210, 150, 255), (150, 230, 190), (230, 170, 230), (200, 255, 210)]
    forbidden = {(0, 0), (S.exit["x"], S.exit["y"])}
    kinds = ("luciole", "fleur", "esprit", "liane", "feuille", "coureuse")
    weights = (3, 2, 2, 3, 3, 2)
    for _ in range(n):
        gx = random.randint(0, S.cols - 1)
        gy = random.randint(0, S.rows - 1)
        if (gx, gy) in forbidden:
            continue
        kind = random.choices(kinds, weights=weights)[0]
        entry = {
            "x": gx + random.uniform(-0.3, 0.3), "y": gy + random.uniform(-0.3, 0.3),
            "kind": kind, "color": random.choice(palette),
            "size": random.uniform(0.10, 0.17), "phase": random.uniform(0, math.tau),
        }
        decor.append(entry)
        if kind == "feuille" and random.random() < 0.5:
            # une petite creature vient grignoter cette feuille juste a cote
            decor.append({
                "x": entry["x"] + random.uniform(-0.15, 0.15), "y": entry["y"] + random.uniform(-0.1, 0.1),
                "kind": "mangeuse", "color": random.choice(palette),
                "size": random.uniform(0.06, 0.09), "phase": random.uniform(0, math.tau),
            })
    return decor


def generate_underwater_decor():
    """Coraux, meduses et fleurs abyssales bioluminescents qui eclairent le
    monde aquatique de belles lumieres, pour que le fond marin ne soit
    jamais plonge dans le noir non plus."""
    palette = [(255, 140, 190), (120, 255, 235), (140, 200, 255), (255, 215, 150), (190, 255, 210)]
    return _generate_glow_decor(("corail", "meduse", "fleur"), palette, n_max=34, n_div=6)


def restart_game():
    reset_pause()
    S.level = 1
    S.lives = 3
    S.inventory_counts = {}
    S.score = 0
    S.narrative_shown = set()
    S.pending_reward = None
    S.reward_popup = None
    S.reward_popup_until = 0.0
    setup_level()


def retry_level():
    """Recommence le niveau actuel (celui ou le joueur est mort) plutot que
    de tout reprendre depuis le niveau 1."""
    reset_pause()
    S.lives = 3
    setup_level()


# ----------------------------------------------------------------------
# Pouvoirs : application des effets (identique au switch JS applyPowerEffect)
# ----------------------------------------------------------------------
def apply_power_effect(d):
    t = now()
    toast("%s !" % d["name"])
    pid = d["id"]
    # Les pouvoirs a duree durent de plus en plus longtemps avec le niveau,
    # pour suivre la montee en puissance du monstre (voir power_duration_multiplier).
    dur = d["duration"] * power_duration_multiplier(S.level)
    if pid == "superforce":
        S.effects["superforce"] = t + dur
        if S.challenge and S.challenge["id"] == "no_force":
            S.challenge["broken"] = True
    elif pid == "invisible":
        S.effects["invisible"] = t + dur
    elif pid == "permute":
        swappable = [m for m in S.monsters if not m.get("mirror_captured")]
        if swappable:
            nearest = min(swappable, key=lambda m: abs(m["x"] - S.player["x"]) + abs(m["y"] - S.player["y"]))
            px, py = S.player["x"], S.player["y"]
            spawn_burst(px, py, count=12, colors=[(255, 200, 80), (255, 255, 255)],
                        speed=2.2, life=0.4, size=0.07, gravity=0)
            spawn_burst(nearest["x"], nearest["y"], count=12, colors=[(255, 200, 80), (255, 255, 255)],
                        speed=2.2, life=0.4, size=0.07, gravity=0)
            S.player["x"], S.player["y"] = nearest["x"], nearest["y"]
            nearest["x"], nearest["y"] = px, py
            S.anim["px"], S.anim["py"] = float(S.player["x"]), float(S.player["y"])
            nearest["anim"]["px"] = float(nearest["x"])
            nearest["anim"]["py"] = float(nearest["y"])
            S.grace_until = t + 0.8
    elif pid == "vitesse":
        S.effects["vitesse"] = t + dur
    elif pid == "gel":
        S.effects["gel"] = t + dur
        for m in S.monsters:
            m["frozen_until"] = t + dur
            spawn_burst(m["x"], m["y"], count=16, colors=ICE_COLORS, speed=2.6,
                        life=0.5, size=0.08, gravity=3, shape="shard")
    elif pid == "vision":
        S.effects["vision"] = t + dur
        spawn_burst(S.player["x"], S.player["y"], count=10, colors=[(255, 255, 255), (200, 240, 255)],
                    speed=1.4, life=0.4, size=0.05, gravity=-0.8)
    elif pid == "radar":
        S.effects["radar"] = t + dur
        spawn_burst(S.player["x"], S.player["y"], count=10, colors=[(120, 255, 180), (255, 255, 255)],
                    speed=1.4, life=0.4, size=0.05, gravity=-0.5)
    elif pid == "bouclier":
        S.effects["shield_charges"] = S.effects.get("shield_charges", 0) + 1
    elif pid == "peur":
        for m in S.monsters:
            m["fear_until"] = t + dur
            spawn_burst(m["x"], m["y"], count=10, colors=[(255, 240, 120), (255, 255, 255)],
                        speed=2.2, life=0.4, size=0.07, gravity=-1.0)
    elif pid == "ralenti":
        for m in S.monsters:
            m["slow_until"] = t + dur
            spawn_burst(m["x"], m["y"], count=10, colors=[(150, 200, 255), (200, 230, 255)],
                        speed=1.2, life=0.5, size=0.07, gravity=1.2)
    elif pid in ("leurre", "clone"):
        c = random_open_cell([(S.player["x"], S.player["y"])])
        S.decoy = {"x": c[0], "y": c[1]}
        spawn_burst(c[0], c[1], count=14, colors=[(255, 255, 255), (200, 220, 255)],
                    speed=1.8, life=0.4, size=0.06, gravity=1)
    elif pid == "teleport":
        c = random_open_cell([(S.player["x"], S.player["y"]), (S.exit["x"], S.exit["y"])])
        spawn_burst(S.player["x"], S.player["y"], count=14,
                    colors=[(180, 220, 255), (255, 255, 255)], speed=2.4, life=0.4, size=0.07, gravity=0)
        S.player["x"], S.player["y"] = c
        S.anim["px"], S.anim["py"] = float(c[0]), float(c[1])
        spawn_burst(c[0], c[1], count=14,
                    colors=[(180, 220, 255), (255, 255, 255)], speed=2.4, life=0.4, size=0.07, gravity=0)
        S.grace_until = t + 1.0
    elif pid == "phase":
        S.effects["phase_charges"] = S.effects.get("phase_charges", 0) + 1
    elif pid == "rapetisse":
        for m in S.monsters:
            m["shrunk_until"] = t + dur
            spawn_burst(m["x"], m["y"], count=12, colors=[(180, 255, 180), (255, 255, 255)],
                        speed=1.6, life=0.45, size=0.06, gravity=2.5)
    elif pid == "dimension":
        S.effects["dimension"] = t + dur
        spawn_burst(S.player["x"], S.player["y"], count=16,
                    colors=[(200, 150, 255), (150, 220, 255), (255, 255, 255)],
                    speed=2.0, life=0.5, size=0.08, gravity=0.5)
    elif pid == "doublepas":
        S.effects["doublepas"] = t + dur
    elif pid == "soin":
        S.lives = min(S.lives + 1, 5)
        spawn_burst(S.player["x"], S.player["y"], count=16,
                    colors=[(76, 175, 80), (200, 255, 200), (255, 255, 255)],
                    speed=1.8, life=0.5, size=0.07, gravity=-1.2)
    elif pid == "confusion":
        for m in S.monsters:
            m["confused_until"] = t + dur
            spawn_burst(m["x"], m["y"], count=10, colors=[(230, 150, 255), (255, 255, 255)],
                        speed=1.8, life=0.45, size=0.06, gravity=0.5)
    elif pid == "aimant":
        S.effects["aimant"] = t + dur
        spawn_burst(S.player["x"], S.player["y"], count=10, colors=[(255, 200, 60), (255, 255, 255)],
                    speed=1.4, life=0.4, size=0.05, gravity=-0.5)
    elif pid == "invincible":
        S.effects["invincible"] = t + dur
    elif pid == "explosion":
        explode_around(S.player["x"], S.player["y"])
        spawn_explosion_fx(S.player["x"], S.player["y"])
        spawn_burst(S.player["x"], S.player["y"], count=24, colors=FIRE_COLORS,
                    speed=4, life=0.48, size=0.1, gravity=3)
        # Physique : un monstre pris dans le souffle (case adjacente) encaisse
        # le meme traitement qu'un coup de Super Force.
        for m in S.monsters[:]:
            if m.get("mirror_captured"):
                continue
            if abs(m["x"] - S.player["x"]) + abs(m["y"] - S.player["y"]) <= 1:
                strike_monster_with_force(m, t)
    elif pid == "mirror":
        place_mirror()
    elif pid == "rembobinage":
        prev = S.prev_pos
        if prev and (prev["x"], prev["y"]) != (S.player["x"], S.player["y"]):
            S.player["x"], S.player["y"] = prev["x"], prev["y"]
            S.anim["px"], S.anim["py"] = float(prev["x"]), float(prev["y"])
            S.grace_until = t + 0.8
            spawn_burst(S.player["x"], S.player["y"], count=14,
                        colors=[(200, 220, 255), (255, 255, 255)], speed=2.2, life=0.4, size=0.07, gravity=0)
        else:
            toast("Rien a annuler pour l'instant.")
    elif pid == "piege_pics":
        S.spike_trap = {"x": S.player["x"], "y": S.player["y"]}
    elif pid == "architecte":
        start_camp_reshuffle("entree_vers_sortie", source="power")
    elif pid == "vampirisme":
        if S.vampire_bat and S.vampire_bat.get("state") == "latched":
            # Une chauve-souris est deja occupee a drainer un monstre mordu :
            # on prolonge simplement le drainage en cours (nouvelles 8
            # secondes) au lieu de perdre la reference au drainage en cours.
            S.vampire_bat["until"] = max(S.vampire_bat["until"], t + VAMPIRE_DRAIN_DURATION)
            S.effects["vampirisme"] = S.vampire_bat["until"]
        else:
            # Tant qu'aucun monstre n'a encore ete mordu, le pouvoir reste
            # actif sans limite de temps : le compte a rebours ne demarre
            # pas encore (voir update_vampire_bat, qui ne le lance qu'au
            # moment de la morsure, pour 8 secondes).
            S.effects["vampirisme"] = float("inf")
            nearest = None
            nearest_dist = None
            for m in S.monsters:
                if m.get("mirror_captured") or m.get("vampire_draining"):
                    continue
                dist = abs(m["x"] - S.player["x"]) + abs(m["y"] - S.player["y"])
                if nearest_dist is None or dist < nearest_dist:
                    nearest, nearest_dist = m, dist
            if nearest is not None and nearest_dist <= VAMPIRE_BAT_CHASE_RADIUS:
                S.vampire_bat = {"state": "chasing", "target": nearest,
                                  "x": float(S.player["x"]), "y": float(S.player["y"]), "until": None}
            else:
                S.vampire_bat = {"state": "orbit", "target": None,
                                  "x": float(S.player["x"]), "y": float(S.player["y"]), "until": None}
        spawn_burst(S.player["x"], S.player["y"], count=16,
                    colors=[(150, 10, 30), (200, 30, 50), (80, 0, 10)],
                    speed=1.6, life=0.55, size=0.07, gravity=-1.2)

    if pid == "bouclier":
        Sound.shield()
    elif pid == "teleport":
        Sound.teleport()
    elif pid == "soin":
        Sound.heal()
    elif pid == "gel":
        Sound.freeze()
    elif pid == "explosion":
        Sound.explosion()
        Sound.multi_wall_break()
        trigger_shake(7, 0.4)
    elif pid == "dimension":
        Sound.dimension()
    elif pid == "mirror":
        Sound.mirror_place()
    elif pid == "rembobinage":
        Sound.teleport()
    else:
        Sound.power_generic()


# ----------------------------------------------------------------------
# Pouvoir "Miroir Piegeur" : on le depose juste a cote du joueur (dans la
# direction regardee si un passage libre y mene, sinon sur le premier cote
# ouvert trouve). Le miroir attend ensuite, immobile, qu'un monstre vienne
# le toucher (voir check_mirror_touch / update_mirror) pour declencher sa
# sequence d'absorption -> retenue -> relachement furieux.
# ----------------------------------------------------------------------
def place_mirror():
    t = now()
    px, py = S.player["x"], S.player["y"]
    facing = S.anim["facing"]
    spot = None
    order = [facing] + [d for d in ("down", "up", "left", "right") if d != facing]
    for d in order:
        if can_move_dir(px, py, d):
            dx, dy, _, _ = DIR_INFO[d]
            spot = (px + dx, py + dy)
            break
    if spot is None:
        spot = (px, py)
    S.mirror = {
        "x": spot[0], "y": spot[1],
        "state": "idle",           # idle -> absorbing -> holding -> releasing -> disparu
        "monster": None,
        "state_since": t,
        "state_until": 0.0,
    }
    spawn_burst(spot[0], spot[1], count=10, colors=[(255, 255, 255), (222, 228, 240)],
                speed=1.3, life=0.4, size=0.06, gravity=1)


# ----------------------------------------------------------------------
# Coups portes au monstre (Super Force au contact, ou souffle d'Explosion).
# Physique (identique a la version HTML) : un monstre GELE est cassant et se
# BRISE en un seul coup (pluie d'eclats de glace), peu importe sa resistance
# habituelle. Sinon, il encaisse des coups jusqu'a son seuil de resistance
# (plus eleve aux niveaux avances) avant d'etre maitrise et repousse.
# ----------------------------------------------------------------------
ICE_COLORS = [(191, 233, 255), (232, 248, 255), (127, 208, 245), (255, 255, 255)]
GOLD_COLORS = [(255, 215, 107), (255, 138, 61), (255, 242, 200)]
WOOD_COLORS = [(107, 83, 64), (74, 55, 40), (43, 31, 22)]
FIRE_COLORS = [(255, 138, 61), (255, 215, 107), (255, 61, 61), (255, 242, 200)]
SPARKLE_COLORS = [(255, 255, 255), (255, 224, 138)]


def launch_monster_from_force(m, t, stun_dur=4.0, max_cells=3):
    """Projette violemment le monstre a l'oppose du joueur : il survole
    plusieurs cases en fracassant les murs qu'il traverse (ils se
    detruisent sous le choc), puis s'ecrase et reste immobile au sol
    pendant stun_dur secondes avant de se relever furieux en poussant un
    cri (voir la reprise du reveil dans update_monsters)."""
    dx = m["x"] - S.player["x"]
    dy = m["y"] - S.player["y"]
    direction = ("right" if dx >= 0 else "left") if abs(dx) >= abs(dy) else ("down" if dy >= 0 else "up")
    ddx, ddy, _, _ = DIR_INFO[direction]
    cx, cy = m["x"], m["y"]
    smashed = 0
    for _ in range(max_cells):
        nx, ny = cx + ddx, cy + ddy
        if index(nx, ny) == -1:
            break
        break_wall(cx, cy, direction)
        mx, my = (cx + nx) / 2.0, (cy + ny) / 2.0
        spawn_burst(mx, my, count=10, colors=[(150, 130, 110), (90, 78, 66), (200, 190, 175)],
                    speed=3.2, life=0.4, size=0.08, gravity=6, shape="square")
        cx, cy = nx, ny
        smashed += 1
    Sound.wall_break() if smashed else Sound.stun()
    trigger_shake(4 + smashed * 2, 0.35)
    spawn_burst(cx, cy, count=20, colors=GOLD_COLORS, speed=3.6, life=0.5, size=0.09, gravity=7, shape="square")
    m["last_cell"] = (m["x"], m["y"])
    m["anim"]["from_x"], m["anim"]["from_y"] = m["x"], m["y"]
    m["anim"]["px"], m["anim"]["py"] = float(m["x"]), float(m["y"])
    m["x"], m["y"] = cx, cy
    m["anim"]["walking"] = True
    m["anim"]["launch"] = True
    m["anim"]["start"] = t
    m["anim"]["duration"] = 0.10 + smashed * 0.045
    m["frozen_until"] = t + stun_dur
    m["force_launch_wake_at"] = t + stun_dur


def strike_monster_with_force(m, t):
    if not m:
        return
    is_frozen_now = t < m.get("frozen_until", 0) and not S.cheat_active
    if is_frozen_now:
        spawn_burst(m["x"], m["y"], count=22, colors=ICE_COLORS, speed=3.4,
                    life=0.62, size=0.11, gravity=8, shape="shard")
        m["force_hits_taken"] = 0
        launch_monster_from_force(m, t)
        toast("Gele, il se brise en eclats et est projete par la Force !")
        Sound.explosion()
        Sound.monster_hurt(m["tier"])
        return

    needed = 1 if S.cheat_active else max(1, m.get("force_hits_needed", 1))
    if t < m.get("shrunk_until", 0):
        needed = max(1, needed // 2)  # Rapetissement : monstre affaibli, plus vite maitrise
    # La puissance des coups du joueur grandit avec le niveau (voir
    # player_force_power), pour compenser la resistance croissante du monstre.
    m["force_hits_taken"] = m.get("force_hits_taken", 0) + player_force_power(S.level)
    Sound.monster_hurt(m["tier"])
    if m["force_hits_taken"] >= needed:
        m["force_hits_taken"] = 0
        launch_monster_from_force(m, t)
        toast("Monstre projete et fracasse contre un mur !")
        Sound.stun()
    else:
        launch_monster_from_force(m, t, stun_dur=4.0, max_cells=2)
        toast("Coup porte ! (%d/%d coups necessaires)" % (m["force_hits_taken"], needed))
        Sound.stun()


# ----------------------------------------------------------------------
# Inventaire (ramassage + selection + utilisation)
# ----------------------------------------------------------------------
def collect_power(d):
    S.inventory_counts[d["id"]] = S.inventory_counts.get(d["id"], 0) + 1
    toast("%s ramasse - TAB pour choisir, ENTREE pour l'utiliser" % d["name"])
    Sound.pickup()
    spawn_burst(S.player["x"], S.player["y"], count=10, colors=[(255, 248, 214), (255, 224, 137), (255, 255, 255)],
                speed=1.6, life=0.38, size=0.06, gravity=1)


def inventory_list():
    return [POWER_BY_ID[pid] for pid in S.inventory_counts if S.inventory_counts[pid] > 0]


def player_has_power():
    """Vrai des que le joueur possede au moins un pouvoir en reserve dans son
    inventaire (meme non utilise pour l'instant) - sert a afficher l'aura de
    fumee grise autour de lui, independamment des auras d'effets actifs."""
    if S.cheat_active:
        return True
    return any(n > 0 for n in S.inventory_counts.values())


def cycle_selection():
    items = inventory_list()
    if not items:
        return
    S.selected_index = (S.selected_index + 1) % len(items)


def activate_selected_power():
    if S.game_over or S.won:
        return
    items = inventory_list()
    if not items:
        return
    if S.selected_index >= len(items):
        S.selected_index = 0
    d = items[S.selected_index]
    S.inventory_counts[d["id"]] -= 1
    if S.inventory_counts[d["id"]] <= 0:
        del S.inventory_counts[d["id"]]
    apply_power_effect(d)
    if S.selected_index >= len(inventory_list()):
        S.selected_index = max(0, len(inventory_list()) - 1)


def check_pickup():
    for p in S.powers[:]:
        if p["x"] == S.player["x"] and p["y"] == S.player["y"]:
            collect_power(p["def"])
            S.powers.remove(p)

    if (S.treasure and not S.treasure_found
            and S.treasure["x"] == S.player["x"] and S.treasure["y"] == S.player["y"]):
        S.treasure_found = True
        toast("Tresor trouve ! Bonus de points a la sortie.", dur=2.2)
        Sound.pickup()
        spawn_burst(S.player["x"], S.player["y"], count=20,
                    colors=[(255, 215, 0), (255, 250, 205), (255, 255, 255)],
                    speed=2.6, life=0.6, size=0.09, gravity=1)

    if (S.bonus_chest and not S.bonus_chest_found
            and S.bonus_chest["x"] == S.player["x"] and S.bonus_chest["y"] == S.player["y"]):
        S.bonus_chest_found = True
        extra = random.choice(POWER_TYPES)
        S.inventory_counts[extra["id"]] = S.inventory_counts.get(extra["id"], 0) + 1
        toast("Coffre mysterieux ouvert : %s obtenu !" % extra["name"], dur=2.4)
        Sound.pickup()
        spawn_burst(S.player["x"], S.player["y"], count=24,
                    colors=[(255, 193, 7), (255, 235, 59), (255, 255, 255)],
                    speed=3.0, life=0.6, size=0.1, gravity=1)


# ----------------------------------------------------------------------
# Collision avec le monstre
# ----------------------------------------------------------------------
def check_monster_collision():
    if S.game_over:
        return
    hit = next((m for m in S.monsters if m["x"] == S.player["x"] and m["y"] == S.player["y"]
                and not m.get("mirror_captured")), None)
    if not hit:
        return
    t = now()
    if t < S.grace_until:
        return
    if effect_active("invincible", t):
        return
    if effect_active("vampirisme", t):
        # Tant que la chauve-souris est active (y compris pendant qu'elle
        # draine un monstre mordu), le joueur est insensible aux attaques.
        return
    if effect_active("dimension", t):
        # dans l'autre dimension, les etres vivants se traversent sans contact
        return
    if t < hit.get("frozen_until", 0):
        # monstre gele : on peut le traverser sans danger, pas de vie perdue
        return

    if effect_active("superforce", t):
        strike_monster_with_force(hit, t)
        return

    if S.effects.get("shield_charges", 0) > 0 or S.cheat_active:
        if not S.cheat_active:
            S.effects["shield_charges"] -= 1
        S.grace_until = t + 1.5
        spawn_burst(S.player["x"], S.player["y"], count=12, colors=[(143, 211, 255), (214, 240, 255)],
                    speed=2.4, life=0.35, size=0.06, gravity=0)
        toast("Le bouclier a absorbe le choc !")
        Sound.shield()
        return

    S.lives -= 1
    if S.challenge and S.challenge["id"] == "no_damage":
        S.challenge["broken"] = True
    Sound.player_hit()
    trigger_shake(6, 0.3)
    spawn_burst(S.player["x"], S.player["y"], count=14, colors=[(255, 82, 82), (183, 28, 28), (255, 138, 128)],
                speed=2.6, life=0.42, size=0.07, gravity=5)
    if S.lives <= 0:
        S.game_over = True
        S.msg = "Perdu ! Le monstre t'a attrape au niveau %d." % S.level
        Sound.game_over()
    else:
        S.player["x"], S.player["y"] = 0, 0
        S.anim["px"], S.anim["py"] = 0.0, 0.0
        S.grace_until = t + 2.0
        toast("Attrape ! Il te reste %d vie(s)." % S.lives)


# ----------------------------------------------------------------------
# Deplacement du joueur
# ----------------------------------------------------------------------
def move(direction, is_auto=False, allow_wall_powers=True):
    if S.game_over or S.won:
        return
    if S.anim["walking"]:
        return

    allowed = can_move_dir(S.player["x"], S.player["y"], direction)
    t = now()
    dx, dy, _, _ = DIR_INFO[direction]
    # allow_wall_powers=False : c'est un pas issu du maintien de la touche
    # (pas un nouvel appui). On avance normalement si le chemin est libre,
    # mais on ne declenche ni traversee ni casse de mur, pour ne pas gaspiller
    # ces pouvoirs a chaque frame tant que la touche reste enfoncee.
    if not allowed and allow_wall_powers:
        if effect_active("dimension", t):
            # dans l'autre dimension, on traverse librement tous les murs
            ni = index(S.player["x"] + dx, S.player["y"] + dy)
            if ni != -1:
                allowed = True
        elif effect_active("superforce", t):
            ni = index(S.player["x"] + dx, S.player["y"] + dy)
            if ni != -1:
                break_wall(S.player["x"], S.player["y"], direction)
                allowed = True
                Sound.wall_break()
                wx, wy = S.player["x"] + dx * 0.5, S.player["y"] + dy * 0.5
                spawn_burst(wx, wy, count=12, colors=WOOD_COLORS, speed=2.6,
                            life=0.45, size=0.07, gravity=9, shape="square")
        elif S.effects.get("phase_charges", 0) > 0 or S.cheat_active:
            ni = index(S.player["x"] + dx, S.player["y"] + dy)
            if ni != -1:
                allowed = True
                if not S.cheat_active:
                    S.effects["phase_charges"] -= 1
    if not allowed:
        return

    from_x, from_y = S.player["x"], S.player["y"]
    S.prev_pos = {"x": from_x, "y": from_y}
    S.player["x"] += dx
    S.player["y"] += dy

    S.anim["facing"] = direction
    S.anim["from_x"] = from_x
    S.anim["from_y"] = from_y
    S.anim["walking"] = True
    S.anim["start"] = t
    base_step = player_base_step_duration(S.level)
    S.anim["duration"] = base_step * 0.625 if effect_active("vitesse", t) else base_step
    if getattr(S, "wall_theme", "pierre") == "eau":
        S.anim["duration"] *= 1.45  # on nage : plus lent qu'une marche normale
        spawn_bubbles(from_x, from_y, count=4)

    S.moves += 1
    S.last_move_time = t  # relance le decompte avant le prochain remaniement automatique du camp
    underwater = getattr(S, "wall_theme", "pierre") == "eau"
    Sound.step(alt=(S.moves % 2 == 0), underwater=underwater)

    if not is_auto and effect_active("doublepas", t):
        S.pending_double_step = direction


def update_player_anim(t):
    if not S.anim["walking"]:
        return
    dt = min(1.0, (t - S.anim["start"]) / S.anim["duration"])
    ease = dt * dt * (3 - 2 * dt)  # smoothstep : legere inertie (accel/decel) au lieu d'un pas lineaire brut
    S.anim["px"] = S.anim["from_x"] + (S.player["x"] - S.anim["from_x"]) * ease
    S.anim["py"] = S.anim["from_y"] + (S.player["y"] - S.anim["from_y"]) * ease
    if dt >= 1.0:
        S.anim["walking"] = False
        S.anim["px"], S.anim["py"] = float(S.player["x"]), float(S.player["y"])
        check_pickup()
        check_monster_collision()
        if not S.game_over and not S.won and S.player["x"] == S.exit["x"] and S.player["y"] == S.exit["y"]:
            S.won = True
            S.exit_open_at = t  # la porte de sortie s'ouvre, le joueur y entre
            finish_level_rewards(t)
            S.msg = "Bravo ! Niveau %d termine en %d coups (+%d points). Niveau suivant..." % (
                S.level, S.moves, S.pending_reward["points"])
            spawn_burst(S.exit["x"], S.exit["y"], count=26,
                        colors=[(255, 202, 40), (76, 175, 80), (233, 69, 96), (255, 255, 255), (66, 165, 245)],
                        speed=3.6, life=0.9, size=0.08, gravity=5)
            Sound.victory()
            S.win_at = t + 1.4
        elif S.pending_double_step and not S.game_over and not S.won:
            d = S.pending_double_step
            S.pending_double_step = None
            move(d, True)
        else:
            S.pending_double_step = None


# ----------------------------------------------------------------------
# IA du monstre (identique a la logique JS : BFS, fuite, confusion...)
# ----------------------------------------------------------------------
def update_monsters(t):
    global _approach_alert_until
    if t >= _approach_alert_until:
        for m in S.monsters:
            if m.get("mirror_captured"):
                continue
            dx = m["x"] - S.player["x"]
            dy = m["y"] - S.player["y"]
            if (dx * dx + dy * dy) ** 0.5 <= APPROACH_ALERT_RADIUS:
                Sound.monster_approaching()
                _approach_alert_until = t + APPROACH_ALERT_COOLDOWN
                break

    for m in S.monsters:
        if m.get("mirror_captured"):
            continue  # aspire/retenu dans le miroir : l'IA est totalement suspendue

        if S.cheat_active:
            m["frozen_until"] = t + 0.5  # "gel" permanent tant que la triche est active

        if m["anim"]["walking"]:
            dt = min(1.0, (t - m["anim"]["start"]) / m["anim"]["duration"])
            m["anim"]["px"] = m["anim"]["from_x"] + (m["x"] - m["anim"]["from_x"]) * dt
            m["anim"]["py"] = m["anim"]["from_y"] + (m["y"] - m["anim"]["from_y"]) * dt
            if dt >= 1.0:
                m["anim"]["walking"] = False
                m["anim"]["px"], m["anim"]["py"] = float(m["x"]), float(m["y"])
                if m["anim"].get("launch"):
                    m["anim"]["launch"] = False
                else:
                    check_monster_collision()
                    check_mirror_touch(m, t)
                    check_spike_trap(m, t)
                    check_decoy_touch(m, t)
            continue

        wake_at = m.get("force_launch_wake_at")
        if wake_at and t >= wake_at:
            m["force_launch_wake_at"] = None
            spawn_burst(m["x"], m["y"], count=16, colors=[(255, 90, 60), (200, 20, 20), (255, 180, 120)],
                        speed=2.8, life=0.42, size=0.08, gravity=3)
            toast("Le monstre se relève, furieux, et pousse un cri !")
            Sound.monster_furious(m["tier"])
            m["next_move_at"] = t

        if t < m.get("frozen_until", 0):
            continue
        if t < m.get("vampire_drain_until", 0):
            continue  # paralyse : il se vide de son energie, incapable d'agir
        if t < m["next_move_at"]:
            continue

        interval = m["base_speed"]
        if t < m.get("slow_until", 0):
            interval *= 1.8
        if t < m.get("shrunk_until", 0):
            interval *= 1.4
        underwater = getattr(S, "wall_theme", "pierre") == "eau"
        if underwater:
            interval *= 1.3

        confused = t < m.get("confused_until", 0)
        feared = t < m.get("fear_until", 0)
        player_hidden = effect_active("invisible", t) or effect_active("dimension", t)

        target = None
        if confused:
            target = random_neighbor_cell(m["x"], m["y"], m["last_cell"])
        elif feared:
            target = flee_neighbor_cell(m["x"], m["y"], S.player["x"], S.player["y"])
        elif S.decoy and random.random() < 0.55:
            target = step_toward_bfs(m["x"], m["y"], S.decoy["x"], S.decoy["y"]) or \
                random_neighbor_cell(m["x"], m["y"], m["last_cell"])
        elif not player_hidden and random.random() < m["smarts"]:
            target = step_toward_bfs(m["x"], m["y"], S.player["x"], S.player["y"]) or \
                random_neighbor_cell(m["x"], m["y"], m["last_cell"])
        else:
            target = random_neighbor_cell(m["x"], m["y"], m["last_cell"])

        if target:
            m["last_cell"] = (m["x"], m["y"])
            m["anim"]["from_x"], m["anim"]["from_y"] = m["x"], m["y"]
            m["x"], m["y"] = target
            m["anim"]["walking"] = True
            m["anim"]["start"] = t
            m["anim"]["duration"] = 0.30 if underwater else 0.22
            if underwater:
                spawn_bubbles(m["last_cell"][0], m["last_cell"][1], count=3)

        m["next_move_at"] = t + interval


# ----------------------------------------------------------------------
# Pouvoir "Miroir Piegeur" : cycle de capture d'un monstre.
# ----------------------------------------------------------------------
def check_mirror_touch(m, t):
    """Appele juste apres qu'un monstre a fini un deplacement : si le miroir
    est pose et encore inactif (idle), et que le monstre vient d'arriver
    exactement sur sa case, on declenche l'absorption."""
    mr = S.mirror
    if not mr or mr["state"] != "idle":
        return
    if m["x"] != mr["x"] or m["y"] != mr["y"]:
        return
    mr["state"] = "absorbing"
    mr["monster"] = m
    mr["state_since"] = t
    mr["state_until"] = t + MIRROR_ABSORB_DURATION
    m["mirror_captured"] = True
    m["anim"]["walking"] = False
    m["anim"]["px"], m["anim"]["py"] = float(m["x"]), float(m["y"])
    toast("Le miroir aspire le monstre...", dur=MIRROR_ABSORB_DURATION + 0.3)
    Sound.mirror_absorb()
    Sound.monster_trapped(m["tier"])


def check_spike_trap(m, t):
    """Appele juste apres qu'un monstre a fini un deplacement : s'il vient
    d'arriver exactement sur la case du Piege a Pics, il est etourdi et le
    piege (a usage unique) est consomme."""
    trap = S.spike_trap
    if not trap or m.get("mirror_captured"):
        return
    if m["x"] != trap["x"] or m["y"] != trap["y"]:
        return
    S.spike_trap = None
    m["frozen_until"] = t + 3.0
    spawn_burst(m["x"], m["y"], count=16, colors=[(190, 80, 70), (120, 40, 30), (255, 200, 180)],
                speed=2.8, life=0.4, size=0.08, gravity=6, shape="square")
    toast("Le piege a pics etourdit le monstre !")
    Sound.stun()


def check_decoy_touch(m, t):
    """Appele juste apres qu'un monstre a fini un deplacement : si le
    clone-leurre (pouvoirs Leurre / Clone Leurre) est present et que le
    monstre vient d'arriver exactement sur sa case, le clone est demasque et
    disparait - c'est desormais le SEUL moyen dont il disparait (plus de
    duree limitee, voir apply_power_effect)."""
    if not S.decoy or m.get("mirror_captured"):
        return
    if m["x"] != S.decoy["x"] or m["y"] != S.decoy["y"]:
        return
    spawn_burst(S.decoy["x"], S.decoy["y"], count=14, colors=[(230, 120, 190), (255, 255, 255)],
                speed=2.4, life=0.4, size=0.07, gravity=2)
    toast("Le monstre a demasque le clone-leurre !")
    S.decoy = None


def update_mirror(t):
    """Fait avancer le miroir dans son cycle : absorption progressive (2s),
    puis retenue prisonniere (8s), puis relachement furieux, avant de
    disparaitre (le miroir ne sert qu'une seule fois par depot)."""
    mr = S.mirror
    if not mr:
        return

    if mr["state"] == "absorbing":
        # petites etincelles blanches qui semblent aspirees dans le miroir,
        # pendant que le monstre se debat (voir draw_monster / mirror_state)
        if random.random() < 0.4:
            spawn_burst(mr["x"], mr["y"], count=2, colors=[(255, 255, 255), (232, 238, 250)],
                        speed=0.5, life=0.28, size=0.035, gravity=-2.0)
        if t >= mr["state_until"]:
            mr["state"] = "holding"
            mr["state_since"] = t
            mr["state_until"] = t + MIRROR_HOLD_DURATION
            spawn_burst(mr["x"], mr["y"], count=16, colors=[(255, 255, 255), (225, 232, 248)],
                        speed=1.8, life=0.5, size=0.07, gravity=0)
            toast("Le monstre est prisonnier du miroir...", dur=2.0)

    elif mr["state"] == "holding":
        if t >= mr["state_until"]:
            mr["state"] = "releasing"
            mr["state_since"] = t
            mr["state_until"] = t + MIRROR_RELEASE_DURATION
            m = mr.get("monster")
            if m is not None and any(mo is m for mo in S.monsters):
                m["mirror_captured"] = False
                m["frozen_until"] = t + MIRROR_RELEASE_DURATION
                m["next_move_at"] = t + MIRROR_RELEASE_DURATION + 0.4
                m["mirror_angry_until"] = t + MIRROR_RELEASE_DURATION
                # on efface les vieux effets residuels (peur, confusion,
                # ralenti, retrecissement) pour que sa sortie furieuse ne
                # soit pas contredite par un effet plus ancien encore actif
                m["fear_until"] = 0.0
                m["confused_until"] = 0.0
                m["slow_until"] = 0.0
                m["shrunk_until"] = 0.0
                m["force_hits_taken"] = 0
            spawn_burst(mr["x"], mr["y"], count=20, colors=[(255, 120, 90), (255, 60, 60), (255, 255, 255)],
                        speed=3.0, life=0.5, size=0.08, gravity=4)
            toast("Le monstre ressort du miroir, furieux !", dur=2.0)
            Sound.mirror_release()
            Sound.monster_furious(m["tier"] if m is not None else 0)

    elif mr["state"] == "releasing":
        if t >= mr["state_until"]:
            S.mirror = None  # le miroir a fini son cycle : il se dissipe


def update_vampire_bat(t):
    """Fait vivre la chauve-souris du pouvoir Vampirisme : elle tourne autour
    du joueur tant qu'aucun monstre n'est a portee, puis fonce mordre le
    premier monstre qui entre dans son rayon de detection (ou qui y etait
    deja au moment de l'activation). Tant qu'aucune morsure n'a eu lieu
    (etats "orbit"/"chasing"), le pouvoir n'a pas de limite de temps : le
    compte a rebours ne demarre pas encore. Le monstre mordu ne meurt pas
    sur le coup : il est paralyse et se vide de son energie pendant
    VAMPIRE_DRAIN_DURATION secondes (08s) avant de se dissiper definitivement
    (et de rendre 1 point de vie, plafonne a 5) - c'est seulement a cet
    instant que le compte a rebours du pouvoir commence vraiment. Tant que la
    morsure est en cours, l'effet "vampirisme" (et donc l'insensibilite du
    joueur aux attaques des monstres, voir check_monster_collision) est
    prolonge jusqu'a la dissipation complete."""
    bat = S.vampire_bat
    if not bat:
        return

    dt = min(0.05, max(0.0, t - bat.get("last_t", t)))
    bat["last_t"] = t

    if bat["state"] == "orbit":
        bat["x"], bat["y"] = float(S.player["x"]), float(S.player["y"])
        nearest, nearest_dist = None, None
        for m in S.monsters:
            if m.get("mirror_captured") or m.get("vampire_draining"):
                continue
            dist = abs(m["x"] - S.player["x"]) + abs(m["y"] - S.player["y"])
            if nearest_dist is None or dist < nearest_dist:
                nearest, nearest_dist = m, dist
        if nearest is not None and nearest_dist <= VAMPIRE_BAT_CHASE_RADIUS:
            bat["state"] = "chasing"
            bat["target"] = nearest
        return

    if bat["state"] == "latched":
        # Le monstre est mordu et paralyse : la chauve-souris reste sur lui
        # et de petites gouttes s'en echappent pendant qu'il se vide.
        target = bat.get("target")
        if target is None or target not in S.monsters:
            bat["state"] = "orbit"
            bat["target"] = None
            return
        bat["x"], bat["y"] = float(target["anim"]["px"]), float(target["anim"]["py"])
        if random.random() < dt * 2.5:
            spawn_burst(target["x"], target["y"], count=1, colors=[(150, 10, 30), (200, 30, 50)],
                        speed=0.8, life=0.4, size=0.05, gravity=-0.5)
        if t >= target.get("vampire_drain_until", 0):
            if target in S.monsters:
                S.monsters.remove(target)
            spawn_burst(target["x"], target["y"], count=22, colors=[(150, 10, 30), (200, 30, 50), (40, 0, 5)],
                        speed=3.2, life=0.55, size=0.09, gravity=4)
            if S.lives < 5:
                S.lives += 1
                toast("Le monstre se dissipe, vide de son energie ! +1 vie", dur=2.2)
            else:
                toast("Le monstre se dissipe, vide de son energie !", dur=2.2)
            Sound.heal()
            if t >= bat["until"]:
                S.vampire_bat = None
            else:
                bat["state"] = "orbit"
                bat["target"] = None
        return

    target = bat.get("target")
    if target is None or target.get("mirror_captured") or target not in S.monsters:
        bat["state"] = "orbit"
        bat["target"] = None
        return
    tx = target["anim"]["px"]
    ty = target["anim"]["py"]
    dx, dy = tx - bat["x"], ty - bat["y"]
    dist = math.hypot(dx, dy)
    if dist < 0.3:
        # Morsure : le monstre est fige et commence a se vider de son
        # energie ; l'effet est prolonge pour couvrir toute la duree du
        # drainage, afin que le joueur reste insensible a ses attaques et
        # aux attaques des autres monstres jusqu'a ce qu'il se dissipe.
        target["vampire_draining"] = True
        target["vampire_drain_start"] = t
        target["vampire_drain_until"] = t + VAMPIRE_DRAIN_DURATION
        # C'est ici, et seulement ici, que le compte a rebours du pouvoir
        # demarre vraiment (bat["until"] etait a None pendant la recherche).
        bat["until"] = max(bat["until"], target["vampire_drain_until"]) if bat.get("until") else target["vampire_drain_until"]
        S.effects["vampirisme"] = bat["until"]
        bat["state"] = "latched"
        bat["target"] = target
        spawn_burst(tx, ty, count=14, colors=[(150, 10, 30), (200, 30, 50), (255, 255, 255)],
                    speed=2.4, life=0.4, size=0.07, gravity=1)
        toast("La chauve-souris mord le monstre : il se vide de son energie !", dur=2.2)
        Sound.monster_hurt(target["tier"])
    elif dist > 0:
        step = min(dist, VAMPIRE_BAT_FLY_SPEED * dt)
        bat["x"] += dx / dist * step
        bat["y"] += dy / dist * step


# ----------------------------------------------------------------------
# Code de triche createur
# ----------------------------------------------------------------------
def handle_cheat_key(ch):
    if S.game_over or S.won:
        return
    if not ch.isalpha():
        return
    S.cheat_buffer = (S.cheat_buffer + ch.upper())[-8:]
    for code in CHEAT_CODES:
        if S.cheat_buffer.endswith(code):
            S.cheat_buffer = ""
            if not S.cheat_active:
                S.cheat_active = True
                toast("Code triche active : pouvoirs illimites pour ce niveau !")
                Sound.power_generic()
            break


# ----------------------------------------------------------------------
# Rendu
# ----------------------------------------------------------------------
def to_screen(gx, gy, cam_x, cam_y):
    sx = GAME_X + (gx - cam_x) * CELL + GAME_W / 2
    sy = GAME_Y + WALL_H + (gy - cam_y) * CELL + FLOOR_H / 2
    return sx, sy


def draw_text(surf, text, font, color, x, y, center=False, shadow=True):
    if shadow:
        sh = font.render(text, True, (0, 0, 0))
        surf.blit(sh, sh.get_rect(center=(x + 1, y + 1)) if center else (x + 1, y + 1))
    img = font.render(text, True, color)
    rect = img.get_rect(center=(x, y)) if center else img.get_rect(topleft=(x, y))
    surf.blit(img, rect)
    return rect


def draw_panel(surf, rect, alpha=90):
    panel = pygame.Surface((rect[2], rect[3]), pygame.SRCALPHA)
    panel.fill((255, 255, 255, alpha))
    surf.blit(panel, (rect[0], rect[1]))


def draw_ice_on_wall(rect, t):
    """Depose un peu de givre/glace directement sur un mur proche d'un
    monstre gele (remplace l'ancien voile bleu qui recouvrait tout l'ecran :
    maintenant seuls les murs autour du monstre gele sont concernes)."""
    shimmer = 0.5 + 0.5 * math.sin(t * 3.0 + rect.x * 0.05 + rect.y * 0.05)
    veil = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    veil.fill((200, 236, 255, int(90 + 45 * shimmer)))
    screen.blit(veil, (rect.x, rect.y))

    n = max(2, int(min(rect.width, rect.height) / 10))
    for i in range(n):
        cx = rect.x + (i + 0.5) * rect.width / n
        cy = rect.y + rect.height / 2
        r = max(1, int(min(rect.width, rect.height) * 0.16))
        pygame.draw.circle(screen, (235, 250, 255), (int(cx), int(cy)), r)
        pygame.draw.circle(screen, (255, 255, 255), (int(cx), int(cy)), max(1, r // 2))


def _draw_dimension_plant(sx, sy, c, t):
    """Liane ou feuille lumineuse et colorée, posee au sol, immobile."""
    pulse = 0.75 + 0.25 * math.sin(t * 2.0 + c["phase"])
    col = c["color"]
    glow_col = tuple(min(255, int(v * (0.7 + 0.3 * pulse))) for v in col)
    if c["kind"] == "liane":
        length = CELL * c["size"] * 3.4
        x2 = sx + math.cos(c["phase"]) * length
        y2 = sy + math.sin(c["phase"]) * length * 0.4
        glow = pygame.Surface((int(length * 2) + 20, int(length * 2) + 20), pygame.SRCALPHA)
        gc = glow.get_width() / 2, glow.get_height() / 2
        pygame.draw.line(glow, (*glow_col, 80), (gc[0] - length / 2, gc[1]), (gc[0] + length / 2, gc[1]),
                          max(4, int(CELL * 0.09)))
        screen.blit(glow, (sx - gc[0], sy - gc[1]))
        pygame.draw.line(screen, glow_col, (sx, sy), (x2, y2), max(2, int(CELL * 0.045)))
        for k in (0.4, 0.75, 1.0):
            pygame.draw.circle(screen, glow_col, (int(sx + (x2 - sx) * k), int(sy + (y2 - sy) * k)),
                                max(1, int(CELL * c["size"] * 0.4)))
    else:  # feuille
        w, h = CELL * c["size"] * 1.6, CELL * c["size"] * 0.9
        glow = pygame.Surface((int(w * 2.4), int(h * 2.4)), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (*glow_col, 90),
                             (glow.get_width() / 2 - w, glow.get_height() / 2 - h, w * 2, h * 2))
        screen.blit(glow, (sx - glow.get_width() / 2, sy - glow.get_height() / 2))
        pygame.draw.ellipse(screen, glow_col, (sx - w / 2, sy - h / 2, w, h))


def draw_dimension_creature(sx, sy, c, t):
    """Petite plante ou creature lumineuse de l'autre dimension (ou du fond
    marin) : lianes/feuilles fixes au sol, esprits/lucioles qui flottent
    sur place, coureuses qui se deplacent en boucle, mangeuses qui
    grignotent une feuille voisine en tremblant legerement."""
    kind = c["kind"]
    if kind in ("liane", "feuille"):
        _draw_dimension_plant(sx, sy, c, t)
        return
    if kind == "coureuse":
        orb = CELL * 0.30
        sx = sx + math.cos(t * 1.1 + c["phase"]) * orb
        sy = sy + math.sin(t * 1.6 + c["phase"] * 1.3) * orb * 0.55
    fast = kind == "mangeuse"
    bob = math.sin(t * (2.6 if fast else 1.8) + c["phase"]) * CELL * (0.025 if fast else 0.08)
    pulse = 0.75 + 0.25 * math.sin(t * (5.5 if fast else 3.0) + c["phase"] * 1.7)
    r = CELL * c["size"] * pulse
    cy = sy + bob
    glow = pygame.Surface((int(r * 5) + 2, int(r * 5) + 2), pygame.SRCALPHA)
    pygame.draw.circle(glow, (*c["color"], 90), (glow.get_width() // 2, glow.get_height() // 2), int(r * 2.2))
    screen.blit(glow, (sx - glow.get_width() / 2, cy - glow.get_height() / 2))
    if kind == "fleur":
        for k in range(5):
            a = k / 5 * 2 * math.pi + c["phase"]
            px = sx + math.cos(a) * r * 1.6
            py = cy + math.sin(a) * r * 1.6
            pygame.draw.circle(screen, c["color"], (int(px), int(py)), max(1, int(r * 0.55)))
    elif kind in ("mangeuse", "coureuse"):
        flap = math.sin(t * 9.0 + c["phase"]) * r * 0.5
        pygame.draw.line(screen, c["color"], (sx - r * 0.4, cy - r * 0.6), (sx - r * 0.9, cy - r * 1.1 - flap),
                          max(1, int(r * 0.2)))
        pygame.draw.line(screen, c["color"], (sx + r * 0.4, cy - r * 0.6), (sx + r * 0.9, cy - r * 1.1 - flap),
                          max(1, int(r * 0.2)))
    pygame.draw.circle(screen, c["color"], (int(sx), int(cy)), max(1, int(r)))
    pygame.draw.circle(screen, (255, 255, 255), (int(sx), int(cy)), max(1, int(r * 0.35)))


_LIGHT_MASK_CACHE = {}


def _build_beam_mask(near_r, far_r, length, steps=34):
    """Construit UNE SEULE FOIS (mis en cache) un masque en forme de cone de
    lampe torche, pointant vers le haut : un coeur etroit et vif pres de
    l'origine (dans la main du joueur) qui s'elargit et s'attenue doucement
    vers le bout du faisceau. Beaucoup d'etapes (steps) -> vrai degrade
    lisse, sans aucune limite nette visible - et comme il est construit une
    seule fois puis simplement tourne/colle a chaque frame, ca reste tres
    rapide."""
    size = int(2 * (length + far_r) + 8)
    m = pygame.Surface((size, size), pygame.SRCALPHA)
    ox = oy = size / 2
    for i in range(steps, 0, -1):
        frac = i / steps          # 1 = bout du faisceau (loin), 0 = origine (la main)
        dist = length * frac
        width = near_r + (far_r - near_r) * frac
        a = int(18 + 232 * (1 - frac) ** 0.7)
        pygame.draw.circle(m, (0, 0, 0, min(255, a)), (int(ox), int(oy - dist)), max(1, int(width)))
    return m


def _get_beam_mask(near_r, far_r, length):
    key = (round(near_r, 1), round(far_r, 1), round(length, 1))
    m = _LIGHT_MASK_CACHE.get(key)
    if m is None:
        m = _build_beam_mask(near_r, far_r, length)
        _LIGHT_MASK_CACHE[key] = m
    return m


_BEAM_ANGLE = {"up": 0, "right": -90, "down": 180, "left": 90}


def _punch_flashlight_beam(veil_surf, local_center, facing, near_r, far_r, length):
    """Perce dans le voile (totalement opaque) un cone lumineux degrade,
    oriente dans la direction regardee par le joueur : c'est la lampe
    torche qu'il tient a la main qui eclaire, pas son corps qui rayonne
    dans toutes les directions."""
    mask = _get_beam_mask(near_r, far_r, length)
    rotated = pygame.transform.rotate(mask, _BEAM_ANGLE.get(facing, 0))
    rect = rotated.get_rect(center=(int(local_center[0]), int(local_center[1])))
    veil_surf.blit(rotated, rect.topleft, special_flags=pygame.BLEND_RGBA_SUB)


def _get_glow_hole_mask(r):
    key = ("hole", round(r, 1))
    m = _LIGHT_MASK_CACHE.get(key)
    if m is None:
        size = int(r * 2) + 2
        m = pygame.Surface((size, size), pygame.SRCALPHA)
        steps = 16
        for i in range(steps, 0, -1):
            frac = i / steps
            rad = r * frac
            a = int(12 + 215 * (1 - frac) ** 1.6)
            pygame.draw.circle(m, (0, 0, 0, a), (size // 2, size // 2), max(1, int(rad)))
        _LIGHT_MASK_CACHE[key] = m
    return m


def _punch_glow_holes(veil_surf, clip, decor, cam_x, cam_y, t, radius_cells=2.3):
    """Perce dans le voile un large halo doux autour de chaque creature/
    plante lumineuse visible : c'est uniquement leur propre lumiere qui
    dissipe l'obscurite (plus aucune torche dans cette dimension)."""
    r = CELL * radius_cells
    mask = _get_glow_hole_mask(r)
    for c in decor:
        sx, sy = to_screen(c["x"], c["y"], cam_x, cam_y)
        if not (clip.x - r <= sx <= clip.right + r and clip.y - r <= sy <= clip.bottom + r):
            continue
        pulse = 0.85 + 0.15 * math.sin(t * 3.0 + c["phase"] * 1.7)
        m = mask if pulse >= 0.98 else pygame.transform.smoothscale(
            mask, (max(1, int(mask.get_width() * pulse)), max(1, int(mask.get_height() * pulse))))
        rect = m.get_rect(center=(int(sx - clip.x), int(sy - clip.y)))
        veil_surf.blit(m, rect.topleft, special_flags=pygame.BLEND_RGBA_SUB)


_DIMENSION_STARDUST = []


def _draw_dimension_stardust(clip, t):
    """Fine poussiere d'etoiles qui derive lentement en fond, independante
    des plantes/creatures posees au sol - donne de la profondeur a la scene."""
    if not _DIMENSION_STARDUST:
        for _ in range(55):
            _DIMENSION_STARDUST.append({
                "x": random.uniform(0, clip.width), "y": random.uniform(0, clip.height),
                "speed": random.uniform(4, 13), "drift": random.uniform(-5, 5),
                "r": random.uniform(0.6, 1.7), "phase": random.uniform(0, math.tau),
            })
    for p in _DIMENSION_STARDUST:
        p["y"] -= p["speed"] / 60.0
        p["x"] += p["drift"] / 60.0
        if p["y"] < -4:
            p["y"] = clip.height + 4
            p["x"] = random.uniform(0, clip.width)
        p["x"] %= clip.width
        tw = 0.5 + 0.5 * math.sin(t * 3.0 + p["phase"])
        col = (int(195 + 45 * tw), int(175 + 55 * tw), 255)
        pygame.draw.circle(screen, col, (int(clip.x + p["x"]), int(clip.y + p["y"])), max(1, int(p["r"])))


def draw_dimension_overlay(clip, player_pos, t):
    """Habille toute la scene d'une teinte irreelle (l'autre dimension).
    Plus de torche ici : c'est uniquement la lumiere propre des plantes et
    creatures qui peuplent cette dimension (S.dimension_decor) qui dissipe
    l'obscurite autour d'elles. Le voile de fond est aussi allege pour que
    le reste ne soit plus un noir total, juste plus sombre."""
    shimmer = 0.5 + 0.5 * math.sin(t * 1.6)
    wash = pygame.Surface((clip.width, clip.height), pygame.SRCALPHA)
    wash.fill((90, 40, 150, int(75 + 20 * shimmer)))
    screen.blit(wash, (clip.x, clip.y))

    veil = pygame.Surface((clip.width, clip.height), pygame.SRCALPHA)
    veil.fill((10, 8, 22, 195))
    cam_x, cam_y = S.anim["px"], S.anim["py"]
    _punch_glow_holes(veil, clip, S.dimension_decor, cam_x, cam_y, t)
    screen.blit(veil, (clip.x, clip.y))

    _draw_dimension_stardust(clip, t)

    pulse = 0.5 + 0.5 * math.sin(t * 1.3)
    rim = pygame.Surface((clip.width, clip.height), pygame.SRCALPHA)
    margin = int(16 + 6 * pulse)
    col = (130, 70, 200, int(65 + 45 * pulse))
    pygame.draw.rect(rim, col, (0, 0, clip.width, margin))
    pygame.draw.rect(rim, col, (0, clip.height - margin, clip.width, margin))
    pygame.draw.rect(rim, col, (0, 0, margin, clip.height))
    pygame.draw.rect(rim, col, (clip.width - margin, 0, margin, clip.height))
    screen.blit(rim, (clip.x, clip.y))


def draw_darkness_overlay(clip, player_pos, t):
    """Stade 'quasiment sombre' (independant de l'autre dimension) : le camp
    est plonge dans un noir total, et seule la lampe torche tenue par le
    joueur en eclaire un cone dans la direction ou il regarde - le reste du
    camp, y compris juste a cote ou derriere lui, reste invisible."""
    veil = pygame.Surface((clip.width, clip.height), pygame.SRCALPHA)
    veil.fill((5, 5, 10, 255))
    local_c = (player_pos[0] - clip.x, player_pos[1] - clip.y)
    near_r = CELL * 0.55
    far_r = CELL * 1.65
    length = CELL * DARK_LIGHT_RADIUS_CELLS * 2.05
    _punch_flashlight_beam(veil, local_c, S.anim["facing"], near_r, far_r, length)
    screen.blit(veil, (clip.x, clip.y))



def draw_caustics(sx, sy, gx, gy, t):
    """Taches de lumiere ondulantes (caustiques) qui dansent sur le fond
    marin, comme le soleil filtre a travers la surface de l'eau en 3D."""
    for i in range(2):
        phase = t * 0.9 + gx * 1.3 + gy * 2.1 + i * 2.4
        ox = math.sin(phase) * CELL * 0.22
        oy = math.cos(phase * 1.3) * CELL * 0.22
        r = CELL * (0.16 + 0.05 * math.sin(phase * 2.0))
        a = int(28 + 14 * math.sin(phase * 1.7))
        glow = pygame.Surface((int(r * 2), int(r * 2)), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (210, 245, 255, max(0, a)), (0, 0, r * 2, r * 2))
        screen.blit(glow, (sx + ox - r, sy + oy - r))


def draw_underwater_overlay(clip, t):
    """Voile bleu translucide + rayons de lumiere obliques qui balayent
    lentement la scene, pour l'impression d'etre vu a travers une colonne
    d'eau (effet 3D de surface qui ondule au-dessus)."""
    wash = pygame.Surface((clip.width, clip.height), pygame.SRCALPHA)
    wash.fill((14, 60, 95, 70))
    screen.blit(wash, (clip.x, clip.y))
    rays = pygame.Surface((clip.width, clip.height), pygame.SRCALPHA)
    ray_w = clip.width * 0.16
    for i in range(-1, 6):
        shift = (t * 26 + i * clip.width * 0.28) % (clip.width + ray_w * 2) - ray_w
        pts = [(shift, 0), (shift + ray_w, 0),
               (shift + ray_w - clip.height * 0.35, clip.height), (shift - clip.height * 0.35, clip.height)]
        pygame.draw.polygon(rays, (200, 235, 255, 16), pts)
    screen.blit(rays, (clip.x, clip.y))


def draw_vampire_overlay(clip, t):
    """Legere vignette rouge sur les bords du camp pendant le pouvoir
    Vampirisme : un cadre translucide, plus marque sur les bords et
    invisible au centre, qui pulse doucement (bords "legerement rouges",
    sans jamais genee la lecture du labyrinthe au milieu de l'ecran)."""
    veil = pygame.Surface((clip.width, clip.height), pygame.SRCALPHA)
    pulse = 0.75 + 0.25 * math.sin(t * 2.4)
    band = max(18, int(clip.width * 0.09))
    col = (150, 10, 24)
    for i in range(band):
        a = int(60 * pulse * (1.0 - i / band))
        if a <= 0:
            continue
        pygame.draw.rect(veil, (*col, a), (i, i, clip.width - 2 * i, clip.height - 2 * i), width=1)
    screen.blit(veil, (clip.x, clip.y))


def draw_game_area(t):
    global GAME_X, GAME_Y
    orig_gx, orig_gy = GAME_X, GAME_Y
    if t < _shake_until:
        amt = _shake_mag * min(1.0, (_shake_until - t) / 0.4)
        GAME_X = orig_gx + random.uniform(-amt, amt)
        GAME_Y = orig_gy + random.uniform(-amt, amt)
    try:
        _draw_game_area_inner(t)
    finally:
        GAME_X, GAME_Y = orig_gx, orig_gy


def _draw_game_area_inner(t):
    cam_x, cam_y = S.anim["px"], S.anim["py"]
    in_dimension = effect_active("dimension", t)

    clip = pygame.Rect(GAME_X, GAME_Y, GAME_W, GAME_H)
    screen.set_clip(clip)
    pygame.draw.rect(screen, (14, 10, 8), clip, border_radius=8)

    gx_min = max(0, int(math.floor(cam_x - VIEW_R - 1)))
    gx_max = min(S.cols - 1, int(math.ceil(cam_x + VIEW_R + 1)))
    gy_min = max(0, int(math.floor(cam_y - VIEW_R - 1)))
    gy_max = min(S.rows - 1, int(math.ceil(cam_y + VIEW_R + 1)))

    # sol (+ leger grain de texture, comme le bruit procedural du HTML), ou
    # fond marin anime (caustiques mouvantes) sur un stade immerge (theme "eau")
    underwater = getattr(S, "wall_theme", "pierre") == "eau"
    in_dimension_floor = effect_active("dimension", t)
    for gy in range(gy_min, gy_max + 1):
        for gx in range(gx_min, gx_max + 1):
            sx, sy = to_screen(gx, gy, cam_x, cam_y)
            if in_dimension_floor:
                base = (13, 8, 26) if (gx + gy) % 2 == 0 else (17, 10, 32)
                pygame.draw.rect(screen, base, (sx - CELL / 2, sy - CELL / 2, CELL, CELL))
                if _noise(gx * 3.1, gy * 2.7) > 0.5:
                    ang = _noise(gx * 1.7, gy * 4.3) * math.pi
                    length = CELL * 0.55
                    x1, y1 = sx + math.cos(ang) * length * 0.5, sy + math.sin(ang) * length * 0.5
                    x2, y2 = sx - math.cos(ang) * length * 0.5, sy - math.sin(ang) * length * 0.5
                    glow_a = int(55 + 45 * math.sin(t * 1.6 + gx * 2.1 + gy * 1.3))
                    crack = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
                    pygame.draw.line(crack, (150, 100, 255, max(20, glow_a)),
                                      (x1 - sx + CELL / 2, y1 - sy + CELL / 2),
                                      (x2 - sx + CELL / 2, y2 - sy + CELL / 2), 2)
                    screen.blit(crack, (sx - CELL / 2, sy - CELL / 2))
                for i in range(3):
                    n1 = _noise(gx * 5 + i, gy * 9 + i)
                    n2 = _noise(gx * 13 + i, gy * 3 + i)
                    px, py = sx - CELL / 2 + n1 * CELL, sy - CELL / 2 + n2 * CELL
                    tw = 0.4 + 0.6 * abs(math.sin(t * 2.0 + gx * 7 + gy * 13 + i))
                    col = (int(150 + 90 * tw), int(140 + 100 * tw), 255)
                    pygame.draw.circle(screen, col, (int(px), int(py)), 1 if i else 2)
                continue
            if underwater:
                color = (20, 74, 102) if (gx + gy) % 2 == 0 else (16, 64, 90)
                pygame.draw.rect(screen, color, (sx - CELL / 2, sy - CELL / 2, CELL, CELL))
                draw_caustics(sx, sy, gx, gy, t)
                continue
            color = COL_PATH_A if (gx + gy) % 2 == 0 else COL_PATH_B
            pygame.draw.rect(screen, color, (sx - CELL / 2, sy - CELL / 2, CELL, CELL))
            for i in range(3):
                n1 = _noise(gx * 3 + i, gy * 7 + i)
                n2 = _noise(gx * 11 + i, gy * 5 + i)
                dx = n1 * CELL - CELL / 2
                dy = n2 * CELL - CELL / 2
                shade = _noise(gx + i, gy - i)
                dot_col = (90, 66, 40, 60) if shade > 0.5 else (230, 205, 150, 60)
                dot = pygame.Surface((6, 6), pygame.SRCALPHA)
                pygame.draw.circle(dot, dot_col, (3, 3), max(1, int(CELL * 0.03)))
                screen.blit(dot, (sx + dx - 3, sy + dy - 3))

    # traces de brulure laissees au sol par le pouvoir Explosion : s'estompent
    # lentement (45s), bien plus discretes que l'animation de flammes elle-meme
    for mrk in S.scorch_marks:
        if gx_min - 1 <= mrk["x"] <= gx_max + 1 and gy_min - 1 <= mrk["y"] <= gy_max + 1:
            sx, sy = to_screen(mrk["x"], mrk["y"], cam_x, cam_y)
            age = t - mrk["born"]
            fade = max(0.0, 1.0 - age / 45.0)
            a = int(150 * fade)
            if a > 0:
                blot = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
                pygame.draw.ellipse(blot, (8, 6, 6, a),
                                     (CELL * 0.06, CELL * 0.16, CELL * 0.88, CELL * 0.7))
                pygame.draw.ellipse(blot, (32, 22, 18, int(a * 0.55)),
                                     (CELL * 0.2, CELL * 0.26, CELL * 0.6, CELL * 0.5))
                screen.blit(blot, (sx - CELL / 2, sy - CELL / 2))

    entities = []

    # murs
    wt = max(4, CELL * 0.16)
    for gy in range(gy_min, gy_max + 1):
        for gx in range(gx_min, gx_max + 1):
            c = S.grid[index(gx, gy)]
            sx, sy = to_screen(gx, gy, cam_x, cam_y)
            half = CELL / 2
            if c["walls"]["top"]:
                r = pygame.Rect(sx - half, sy - half - wt / 2, CELL, wt)
                entities.append((gy - 0.5, lambda r=r, gx=gx, gy=gy: draw_wall(r, gx, gy, "top")))
            if c["walls"]["left"]:
                r = pygame.Rect(sx - half - wt / 2, sy - half, wt, CELL)
                entities.append((gy + 0.49, lambda r=r, gx=gx, gy=gy: draw_wall(r, gx, gy, "left")))
            if c["walls"]["right"]:
                r = pygame.Rect(sx + half - wt / 2, sy - half, wt, CELL)
                entities.append((gy + 0.49, lambda r=r, gx=gx, gy=gy: draw_wall(r, gx, gy, "right")))
            if c["walls"]["bottom"]:
                r = pygame.Rect(sx - half, sy + half - wt / 2, CELL, wt)
                entities.append((gy + 0.5, lambda r=r, gx=gx, gy=gy: draw_wall(r, gx, gy, "bottom")))

    # portes (vraie porte animee : cadre + battants + aura + lianes du theme)
    if gx_min <= S.exit["x"] <= gx_max and gy_min <= S.exit["y"] <= gy_max:
        sx, sy = to_screen(S.exit["x"], S.exit["y"], cam_x, cam_y)
        entities.append((S.exit["y"] + 0.4, lambda sx=sx, sy=sy, t=t: draw_door(sx, sy, "out", t)))
    if gx_min <= 0 <= gx_max and gy_min <= 0 <= gy_max:
        sx, sy = to_screen(0, 0, cam_x, cam_y)
        entities.append((0.4, lambda sx=sx, sy=sy, t=t: draw_door(sx, sy, "in", t)))

    # pouvoirs au sol
    for p in S.powers:
        if gx_min <= p["x"] <= gx_max and gy_min <= p["y"] <= gy_max:
            sx, sy = to_screen(p["x"], p["y"], cam_x, cam_y)
            entities.append((p["y"], lambda sx=sx, sy=sy, d=p["def"]: draw_power_orb(sx, sy, d, t)))

    # tresor secret (objectif optionnel, facultatif)
    if (S.treasure and not S.treasure_found
            and gx_min <= S.treasure["x"] <= gx_max and gy_min <= S.treasure["y"] <= gy_max):
        sx, sy = to_screen(S.treasure["x"], S.treasure["y"], cam_x, cam_y)
        entities.append((S.treasure["y"], lambda sx=sx, sy=sy: draw_treasure_marker(sx, sy, t)))

    # coffre bonus (evenement aleatoire rare)
    if (S.bonus_chest and not S.bonus_chest_found
            and gx_min <= S.bonus_chest["x"] <= gx_max and gy_min <= S.bonus_chest["y"] <= gy_max):
        sx, sy = to_screen(S.bonus_chest["x"], S.bonus_chest["y"], cam_x, cam_y)
        entities.append((S.bonus_chest["y"], lambda sx=sx, sy=sy: draw_bonus_chest_marker(sx, sy, t)))

    # leurre
    if S.decoy:
        sx, sy = to_screen(S.decoy["x"], S.decoy["y"], cam_x, cam_y)
        entities.append((S.decoy["y"], lambda sx=sx, sy=sy: draw_decoy(sx, sy, t)))

    # flammes du pouvoir Explosion : courte animation, en plus de la trace de
    # brulure (dessinee plus tot, avec le sol) et des etincelles (particules)
    for f in S.fire_fx:
        if gx_min - 1 <= f["x"] <= gx_max + 1 and gy_min - 1 <= f["y"] <= gy_max + 1:
            sx, sy = to_screen(f["x"], f["y"], cam_x, cam_y)
            age = t - f["born"]
            entities.append((f["y"] + 0.3, lambda sx=sx, sy=sy, age=age: draw_explosion_fire(sx, sy, age, t)))

    # chauve-souris du pouvoir Vampirisme
    if S.vampire_bat:
        bat = S.vampire_bat
        bx, by = to_screen(bat["x"], bat["y"], cam_x, cam_y)
        orbiting = bat["state"] == "orbit"
        entities.append((bat["y"] - 0.4,
                          lambda bx=bx, by=by, orbiting=orbiting: draw_vampire_bat(bx, by, t, orbiting)))

    # miroir piegeur : pose au sol, s'illumine pendant qu'il absorbe/retient
    # un monstre (voir draw_mirror). Dessine juste avant le monstre concerne
    # pour que celui-ci apparaisse par-dessus tant qu'il est encore visible.
    if S.mirror:
        msx, msy = to_screen(S.mirror["x"], S.mirror["y"], cam_x, cam_y)
        entities.append((S.mirror["y"] - 0.05,
                          lambda msx=msx, msy=msy, mirror=S.mirror: draw_mirror(msx, msy, t, mirror)))

    # monstre(s) : dans l'autre dimension, on ne voit plus leur corps mais
    # l'energie qu'ils degagent (voir draw_monster_energy) ; ils continuent
    # d'agir normalement (mais sans nous detecter, voir update_monsters)
    for mo in S.monsters:
        mx, my = mo["anim"]["px"], mo["anim"]["py"]
        sx, sy = to_screen(mx, my, cam_x, cam_y)
        frozen = now() < mo.get("frozen_until", 0)
        drain_prog = 0.0
        if mo.get("vampire_draining") and now() < mo.get("vampire_drain_until", 0):
            drain_prog = min(1.0, (t - mo.get("vampire_drain_start", t)) / VAMPIRE_DRAIN_DURATION)
        shrunk = now() < mo.get("shrunk_until", 0)
        m_state, m_since = None, 0.0
        if S.mirror and S.mirror.get("monster") is mo:
            m_state = S.mirror["state"]
            m_since = t - S.mirror["state_since"]
        arc_offset = 0.0
        if mo["anim"].get("launch") and mo["anim"]["walking"]:
            prog = min(1.0, (t - mo["anim"]["start"]) / mo["anim"]["duration"])
            arc_offset = math.sin(prog * math.pi) * CELL * 0.9  # saute en arc pendant le vol
        sy -= arc_offset
        if in_dimension:
            entities.append((my, lambda sx=sx, sy=sy, tier=mo["tier"]: draw_monster_energy(sx, sy, tier, t)))
        else:
            entities.append((my, lambda sx=sx, sy=sy, tier=mo["tier"], since=mo["since"], frozen=frozen,
                              m_state=m_state, m_since=m_since, drain_prog=drain_prog, shrunk=shrunk:
                              draw_monster(sx, sy, tier, since, t, frozen, spooky=S.dark_level,
                                           mirror_state=m_state, mirror_since=m_since, drain_prog=drain_prog,
                                           shrunk=shrunk)))

    # petites creatures inoffensives qui n'existent que dans l'autre dimension
    if in_dimension:
        for c in S.dimension_decor:
            if gx_min - 1 <= c["x"] <= gx_max + 1 and gy_min - 1 <= c["y"] <= gy_max + 1:
                sx, sy = to_screen(c["x"], c["y"], cam_x, cam_y)
                entities.append((c["y"], lambda sx=sx, sy=sy, c=c, t=t: draw_dimension_creature(sx, sy, c, t)))
    elif underwater:
        for c in S.underwater_decor:
            if gx_min - 1 <= c["x"] <= gx_max + 1 and gy_min - 1 <= c["y"] <= gy_max + 1:
                sx, sy = to_screen(c["x"], c["y"], cam_x, cam_y)
                entities.append((c["y"], lambda sx=sx, sy=sy, c=c, t=t: draw_dimension_creature(sx, sy, c, t)))

    # joueur (avec les auras des pouvoirs actifs : bouclier, autre dimension, vitesse...)
    sx, sy = to_screen(S.anim["px"], S.anim["py"], cam_x, cam_y)
    player_screen = (sx, sy)
    if in_dimension:
        S.player_trail.append({"x": S.anim["px"], "y": S.anim["py"], "t": t})
        if len(S.player_trail) > 16:
            S.player_trail.pop(0)
        for p in S.player_trail:
            age = t - p["t"]
            if age > 0.6:
                continue
            frac = 1.0 - age / 0.6
            tx, ty = to_screen(p["x"], p["y"], cam_x, cam_y)
            r = 3 + 5 * frac
            glow = pygame.Surface((int(r * 3) + 2, int(r * 3) + 2), pygame.SRCALPHA)
            gc = glow.get_width() // 2
            pygame.draw.circle(glow, (255, 221, 90, int(140 * frac)), (gc, gc), max(1, int(r)))
            screen.blit(glow, (tx - gc, ty - gc))
    elif S.player_trail:
        S.player_trail = []
    walk_phase = ((t - S.anim["start"]) / S.anim["duration"]) * math.pi * 2 if S.anim["walking"] else 0.0
    tn = now()
    ghost = effect_active("invisible", tn)
    active = {
        "superforce": effect_active("superforce", tn),
        "shield": S.effects.get("shield_charges", 0) > 0 or S.cheat_active,
        "phase": S.effects.get("phase_charges", 0) > 0 or S.cheat_active,
        "invincible": effect_active("invincible", tn),
        "vitesse": effect_active("vitesse", tn),
        "dimension": effect_active("dimension", tn),
        "vampirisme": effect_active("vampirisme", tn),
    }
    has_power = player_has_power()
    entities.append((S.anim["py"], lambda sx=sx, sy=sy, facing=S.anim["facing"], wp=walk_phase, ghost=ghost,
                      active=active, t=t: draw_player(sx, sy, facing, wp, ghost, active, t,
                                                        torch=S.dark_level,
                                                        has_power=has_power)))

    # particules (eclats de mur, glace, bouclier, victoire...)
    tp = now()
    for p in S.particles:
        px, py, rot, alpha = particle_state(p, tp)
        s2 = to_screen(px, py, cam_x, cam_y)
        entities.append((py, lambda s2=s2, p=p, rot=rot, alpha=alpha: draw_particle(s2[0], s2[1], p, rot, alpha)))

    entities.sort(key=lambda e: e[0])
    for _, fn in entities:
        fn()

    # givre localise sur les murs adjacents a un monstre gele (au lieu d'un
    # voile bleu recouvrant tout l'ecran) : seuls les murs proches du monstre
    # gele se couvrent de glace.
    for mo in S.monsters:
        if now() >= mo.get("frozen_until", 0):
            continue
        mx, my = mo["x"], mo["y"]
        if not (gx_min <= mx <= gx_max and gy_min <= my <= gy_max):
            continue
        c = S.grid[index(mx, my)]
        msx, msy = to_screen(mx, my, cam_x, cam_y)
        half = CELL / 2
        wall_rects = []
        if c["walls"]["top"]:
            wall_rects.append(pygame.Rect(msx - half, msy - half - wt / 2, CELL, wt))
        if c["walls"]["left"]:
            wall_rects.append(pygame.Rect(msx - half - wt / 2, msy - half, wt, CELL))
        if c["walls"]["right"]:
            wall_rects.append(pygame.Rect(msx + half - wt / 2, msy - half, wt, CELL))
        if c["walls"]["bottom"]:
            wall_rects.append(pygame.Rect(msx - half, msy + half - wt / 2, CELL, wt))
        for r in wall_rects:
            draw_ice_on_wall(r, t)

    if in_dimension:
        draw_dimension_overlay(clip, player_screen, t)
    elif S.dark_level:
        draw_darkness_overlay(clip, player_screen, t)
    elif getattr(S, "wall_theme", "pierre") == "eau":
        draw_underwater_overlay(clip, t)

    if effect_active("vampirisme", t):
        draw_vampire_overlay(clip, t)

    if in_dimension:
        snap = screen.subsurface(clip).copy()
        distorted = _apply_wave_distortion(snap, t)
        screen.blit(distorted, clip.topleft)

    screen.blit(_get_vignette(GAME_W, GAME_H), (GAME_X, GAME_Y))

    if effect_active("radar", now()) or effect_active("aimant", now()):
        draw_radar(cam_x, cam_y)
    draw_minimap(cam_x, cam_y, show_monsters=effect_active("vision", now()))
    if S.cheat_active:
        draw_text(screen, "TRICHE ACTIVE", FONT_TINY, COL_CHEAT, GAME_X + GAME_W / 2, GAME_Y + 14, center=True)

    screen.set_clip(None)
    pygame.draw.rect(screen, (0, 0, 0), clip, width=3, border_radius=8)


def _band_gradient_rect(surf, rect, colors):
    """Remplit rect avec un degrade vertical approxime par bandes de
    couleurs unies (rapide), plutot qu'un vrai degrade pixel par pixel."""
    x, y, w, h = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
    if w <= 0 or h <= 0:
        return
    n = len(colors)
    band_h = max(1, h // n)
    for i, c in enumerate(colors):
        yy = y + i * band_h
        hh = band_h if i < n - 1 else (h - band_h * (n - 1))
        if hh > 0:
            pygame.draw.rect(surf, c, (x, yy, w, hh))


WALL_PALETTES = {
    "pierre": {
        "front": [(107, 83, 64), (74, 55, 40), (36, 26, 18)],
        "top": [(138, 106, 74), (107, 83, 64)],
    },
    "plante": {
        "front": [(84, 107, 61), (55, 78, 42), (28, 42, 22)],
        "top": [(122, 150, 82), (84, 107, 61)],
    },
    "glace": {
        "front": [(196, 228, 247), (146, 195, 227), (92, 145, 181)],
        "top": [(224, 243, 255), (196, 228, 247)],
    },
    "lave": {
        "front": [(64, 34, 24), (42, 22, 16), (20, 11, 8)],
        "top": [(94, 52, 32), (64, 34, 24)],
    },
    "eau": {
        "front": [(18, 62, 92), (12, 44, 72), (6, 26, 48)],
        "top": [(40, 110, 140), (18, 62, 92)],
    },
}

_WALL_SIDE_SEED = {"top": 0.0, "left": 1.7, "right": 3.4, "bottom": 5.1}


def _draw_wall_vines(front_rect, top_rect, seed):
    """Quelques feuilles/lianes vertes accrochees au mur, toujours placees au
    meme endroit pour un mur donne (motif determine par 'seed', pas de
    scintillement quand la camera bouge)."""
    fx, fy, fw, fh = front_rect
    leaf_cols = [(58, 122, 58), (74, 143, 68), (100, 163, 74)]
    n = 3 + int(_noise(seed, 1.0) * 3)
    for i in range(n):
        nx = _noise(seed + i * 2.7, 2.3)
        ny = _noise(seed + i * 1.3, 5.9)
        lx = fx + nx * fw
        ly = fy + fh * 0.25 + ny * fh * 0.75
        r = max(2, int(min(fw, fh) * (0.10 + 0.05 * _noise(seed + i, 9.1))))
        col = leaf_cols[i % len(leaf_cols)]
        pygame.draw.ellipse(screen, col, (lx - r, ly - r * 0.7, r * 2, r * 1.4))
    tx, ty, tw, th = top_rect
    if tw > 0 and th > 0:
        gx2 = tx + _noise(seed + 4.4, 8.8) * tw
        gy2 = ty + th * 0.5
        pygame.draw.circle(screen, (90, 150, 70), (int(gx2), int(gy2)), max(1, int(min(tw, th) * 0.18)))


def _draw_wall_dimension_vines(front_rect, top_rect, seed, t):
    """Lianes et pousses lumineuses aux couleurs vives, accrochees au mur,
    visibles uniquement dans l'autre dimension - s'ajoutent par-dessus
    n'importe quel theme de mur pour l'embellir."""
    fx, fy, fw, fh = front_rect
    palette = [(255, 120, 200), (140, 255, 210), (150, 190, 255), (255, 210, 120), (210, 150, 255)]
    n = 2 + int(_noise(seed + 20, 1.0) * 3)
    for i in range(n):
        nx = _noise(seed + i * 3.7 + 50, 2.3)
        x0 = fx + nx * fw
        bot_y = fy + fh * (0.35 + 0.5 * _noise(seed + i, 6.1))
        sway = math.sin(t * 1.3 + seed + i * 1.9) * fw * 0.07
        col = palette[i % len(palette)]
        pulse = 0.6 + 0.4 * math.sin(t * 2.2 + seed * 2 + i)
        glow_col = tuple(min(255, int(v * (0.7 + 0.3 * pulse))) for v in col)
        pygame.draw.line(screen, glow_col, (x0, fy), (x0 + sway, bot_y), max(2, int(fw * 0.05)))
        r = max(2, int(fw * 0.09 * (0.8 + 0.3 * pulse)))
        pygame.draw.circle(screen, glow_col, (int(x0 + sway), int(bot_y)), r)
    tx, ty, tw, th = top_rect
    if tw > 0 and th > 0 and _noise(seed + 77, 3.3) > 0.4:
        gx2 = tx + _noise(seed + 8.8, 5.5) * tw
        gy2 = ty + th * 0.5
        pygame.draw.circle(screen, palette[int(seed) % len(palette)], (int(gx2), int(gy2)),
                            max(1, int(min(tw, th) * 0.16)))


def _draw_wall_frost_sparkle(front_rect, seed):
    """Petits eclats de givre scintillants sur un mur de glace."""
    fx, fy, fw, fh = front_rect
    n = 2 + int(_noise(seed, 3.0) * 3)
    for i in range(n):
        nx = _noise(seed + i * 3.1, 1.0)
        ny = _noise(seed + i * 1.9, 6.7)
        px = fx + nx * fw
        py = fy + fh * 0.2 + ny * fh * 0.7
        r = max(1, int(min(fw, fh) * 0.07))
        pygame.draw.circle(screen, (255, 255, 255), (int(px), int(py)), r)


def _draw_wall_lava_cracks(front_rect, seed, t):
    """Fissures de lave incandescente qui pulsent doucement au fil du temps,
    comme si le mur etait fait de roche a demi fondue."""
    fx, fy, fw, fh = front_rect
    n = 2 + int(_noise(seed, 2.0) * 2)
    for i in range(n):
        nx = _noise(seed + i * 2.2, 0.6)
        ny1 = _noise(seed + i * 1.1, 3.3)
        ny2 = _noise(seed + i * 1.1, 4.4)
        x0 = fx + nx * fw
        y0 = fy + fh * (0.15 + ny1 * 0.35)
        y1 = fy + fh * (0.55 + ny2 * 0.4)
        pulse = 0.55 + 0.45 * math.sin(t * 2.2 + seed * 3.0 + i)
        glow = (255, int(90 + 90 * pulse), int(20 + 40 * pulse))
        pygame.draw.line(screen, glow, (x0, y0), (x0, y1), max(1, int(min(fw, fh) * 0.06)))
        pygame.draw.circle(screen, glow, (int(x0), int(y1)), max(1, int(min(fw, fh) * 0.09)))


def _draw_wall_coral(front_rect, top_rect, seed, t):
    """Corail, algues ondulantes et petites bulles qui s'echappent des
    fissures d'un mur/recif immerge (theme 'eau')."""
    fx, fy, fw, fh = front_rect
    algae_col = [(30, 150, 110), (40, 175, 120), (60, 190, 140)]
    coral_col = [(230, 120, 120), (240, 150, 90), (200, 100, 160)]
    n = 3 + int(_noise(seed, 1.0) * 3)
    for i in range(n):
        nx = _noise(seed + i * 2.7, 2.3)
        bx = fx + nx * fw
        base_y = fy + fh
        sway = math.sin(t * 1.6 + seed + i * 1.7) * fw * 0.05
        h = fh * (0.35 + 0.35 * _noise(seed + i, 9.1))
        pygame.draw.line(screen, random.Random(int(seed * 99 + i)).choice(algae_col),
                          (bx, base_y), (bx + sway, base_y - h), max(2, int(fw * 0.05)))
        if _noise(seed + i * 3.3, 4.2) > 0.55:
            r = max(2, int(fw * 0.06))
            pygame.draw.circle(screen, random.Random(int(seed * 47 + i)).choice(coral_col),
                                (int(bx - sway * 0.4), int(base_y - h * 0.15)), r)
    # petites bulles qui remontent le long du mur, position cyclique selon t
    for i in range(2):
        bub_seed = seed * 3.1 + i * 5.5
        rise = (t * 0.35 + _noise(bub_seed, 1.0)) % 1.0
        bx = fx + _noise(bub_seed, 2.0) * fw
        by = fy + fh * (1.0 - rise)
        r = max(1, int(fw * 0.035 * (0.5 + rise)))
        alpha = int(180 * (1.0 - rise))
        bsurf = pygame.Surface((r * 3, r * 3), pygame.SRCALPHA)
        pygame.draw.circle(bsurf, (190, 230, 255, alpha), (r * 1.5, r * 1.5), r, width=1)
        screen.blit(bsurf, (bx - r * 1.5, by - r * 1.5))


def draw_wall(rect, gx=0, gy=0, side="top"):
    """Dessine un vrai 'bloc' de mur en pseudo-3D : ombre de contact au sol,
    face avant (verticale, degradee sombre) et face du dessus (plus claire,
    vue en plongee) - exactement le principe de wallBox() dans la version
    HTML, pour qu'on distingue un mur d'une simple dalle au sol. L'aspect
    (pierre / plante / glace / lave) depend du theme tire au hasard pour
    ce niveau (S.wall_theme)."""
    x, y, w, hf = rect.x, rect.y, rect.w, rect.h
    h = WALL_H
    cy_max = y + hf
    theme = getattr(S, "wall_theme", "pierre")
    pal = WALL_PALETTES.get(theme, WALL_PALETTES["pierre"])

    # ombre de contact au sol, juste devant le mur
    shadow = pygame.Surface((w + 2, max(2, int(h * 0.14))), pygame.SRCALPHA)
    shadow.fill((0, 0, 0, 90))
    screen.blit(shadow, (x - 1, cy_max))

    # face avant (verticale)
    front_rect = (x, cy_max - h, w, h)
    _band_gradient_rect(screen, front_rect, pal["front"])
    pygame.draw.rect(screen, (0, 0, 0), front_rect, width=1)

    # face du dessus (plus claire, donne la sensation d'epaisseur/hauteur)
    top_rect = (x, y - h, w, hf)
    _band_gradient_rect(screen, top_rect, pal["top"])
    pygame.draw.rect(screen, (0, 0, 0, 90), top_rect, width=1)

    if theme != "pierre":
        seed = gx * 4.13 + gy * 7.91 + _WALL_SIDE_SEED.get(side, 0.0)
        if theme == "plante":
            _draw_wall_vines(front_rect, top_rect, seed)
        elif theme == "glace":
            _draw_wall_frost_sparkle(front_rect, seed)
        elif theme == "lave":
            _draw_wall_lava_cracks(front_rect, seed, now())
        elif theme == "eau":
            _draw_wall_coral(front_rect, top_rect, seed, now())

    if effect_active("dimension", now()):
        seed = gx * 4.13 + gy * 7.91 + _WALL_SIDE_SEED.get(side, 0.0) + 30.0
        _draw_wall_dimension_vines(front_rect, top_rect, seed, now())


def _ease_out_cubic(x):
    x = max(0.0, min(1.0, x))
    return 1.0 - (1.0 - x) ** 3


# Duree (s) des trois phases de l'animation de la porte d'entree : ouverture,
# maintien ouverte (le temps que le joueur sorte du camp), puis disparition.
GATE_IN_OPEN_DUR = 0.6
GATE_IN_HOLD_DUR = 1.7
GATE_IN_FADE_DUR = 0.6
GATE_OUT_OPEN_DUR = 0.4


def compute_gate_anim(kind, t):
    """Calcule l'etat d'animation d'une porte : (ouverture 0->1, opacite 0->1,
    visible). 'in' = porte d'entree (apparait, s'ouvre, le joueur sort du
    camp, puis elle se referme et disparait) ; 'out' = porte de sortie
    (reste fermee jusqu'a ce que le joueur l'atteigne, puis s'ouvre)."""
    if kind == "in":
        start = getattr(S, "gate_in_appear_at", None)
        if start is None:
            return 0.0, 0.0, False
        e = t - start
        total = GATE_IN_OPEN_DUR + GATE_IN_HOLD_DUR + GATE_IN_FADE_DUR
        if e < 0 or e > total:
            return 0.0, 0.0, False
        if e < GATE_IN_OPEN_DUR:
            return _ease_out_cubic(e / GATE_IN_OPEN_DUR), 1.0, True
        if e < GATE_IN_OPEN_DUR + GATE_IN_HOLD_DUR:
            return 1.0, 1.0, True
        f = (e - GATE_IN_OPEN_DUR - GATE_IN_HOLD_DUR) / GATE_IN_FADE_DUR
        return 1.0, max(0.0, 1.0 - f), True
    else:
        start = getattr(S, "exit_open_at", None)
        if start is None:
            return 0.0, 1.0, True
        e = t - start
        return min(1.0, e / GATE_OUT_OPEN_DUR), 1.0, True


def door_theme_colors():
    """Cadre (pierre/bois) + lianes-feuilles de la porte, assortis au theme
    des murs du stade/camp en cours (S.wall_theme) : les portes reprennent
    ainsi les couleurs du decor plutot que rester toujours identiques."""
    theme = getattr(S, "wall_theme", "pierre")
    pal = WALL_PALETTES.get(theme, WALL_PALETTES["pierre"])
    frame = pal["front"]
    if theme == "plante":
        vines = [(58, 122, 58), (74, 143, 68), (100, 163, 74), (140, 190, 90)]
    elif theme == "glace":
        vines = [(196, 228, 247), (224, 243, 255), (146, 195, 227)]
    elif theme == "lave":
        vines = [(255, 140, 60), (255, 90, 40), (220, 60, 30)]
    elif theme == "eau":
        vines = [(60, 190, 140), (40, 175, 120), (30, 150, 110)]
    else:
        vines = [(120, 150, 90), (95, 125, 70), (140, 170, 100)]
    return frame, vines


def _draw_door_vines(surf, cx, top, half, bot, vine_cols, seed):
    """Petites lianes/feuilles accrochees au cadre de la porte (haut de
    l'arche + montants), meme principe que _draw_wall_vines : position
    toujours identique pour une porte donnee (pas de scintillement)."""
    n = 5 + int(_noise(seed, 3.1) * 4)
    h = bot - top
    for i in range(n):
        n1 = _noise(seed + i * 2.3, 1.7)
        n2 = _noise(seed + i * 4.1, 5.9)
        side = -1 if n1 < 0.5 else 1
        along = n2  # 0..1 le long du montant, du haut vers le bas
        px = cx + side * (half + 2 - along * 4)
        py = top + 6 + along * (h * 0.62)
        leaf_col = vine_cols[i % len(vine_cols)]
        droop = 5 + n1 * 7
        pygame.draw.line(surf, (*leaf_col, 230), (px, py), (px + side * 2, py + droop), 2)
        for k in range(2):
            lx = px + side * (2 + k * 2)
            ly = py + droop * (0.4 + k * 0.5)
            pygame.draw.ellipse(surf, (*leaf_col, 220), (lx - 3, ly - 2, 6, 4))
    # une guirlande de feuilles le long du haut de l'arche
    for i in range(7):
        f = i / 6.0
        ax = cx - half * 0.85 + f * half * 1.7
        ay = top - 2 + math.sin(f * math.pi) * -3
        leaf_col = vine_cols[(i + 1) % len(vine_cols)]
        pygame.draw.ellipse(surf, (*leaf_col, 220), (ax - 3.5, ay - 2.5, 7, 5))


def draw_door(sx, sy, kind, t):
    """Dessine une vraie petite porte (cadre en arche + deux battants qui
    s'ouvrent, lianes/feuilles assorties au theme du stade, aura lumineuse
    qui degage une jolie lumiere) plutot qu'un simple rond de couleur.
    kind = 'in' (entree du camp, lumiere verte) ou 'out' (sortie, lumiere
    doree)."""
    open_amount, fade, visible = compute_gate_anim(kind, t)
    if not visible or fade <= 0.01:
        return
    frame_cols, vine_cols = door_theme_colors()
    glow_col = COL_DOOR_IN if kind == "in" else COL_DOOR_OUT

    w = CELL * 0.56
    h = CELL * 1.08
    cx = sx
    top = sy - h * 0.80
    bot = sy + h * 0.20
    half = w / 2

    size = int(max(w, h) * 2.6)
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    ox, oy = size / 2 - cx, size / 2 - sy
    cx, top, bot = cx + ox, top + oy, bot + oy

    def A(a):
        return max(0, min(255, int(a * fade)))

    # --- aura lumineuse pulsante, plus intense quand la porte est ouverte ---
    pulse = 0.85 + 0.15 * math.sin(t * 2.4 + (0.0 if kind == "in" else 1.7))
    glow_r = w * (1.3 + open_amount * 0.9) * pulse
    _radial_glow(surf, (cx, sy + oy - h * 0.30), glow_r, glow_col, A(55 + open_amount * 70), steps=7)

    # --- ombre au sol ---
    pygame.draw.ellipse(surf, (0, 0, 0, A(90)), (cx - half * 1.1, bot - 4, half * 2.2, 10))

    # --- cadre en arche (couleurs du theme du stade) : coins arrondis en haut
    # seulement, base plate au sol, pour vraiment ressembler a une porte ---
    arch_r = int(half * 0.9)
    frame_rect = (cx - half - 5, top - 5, w + 10, h + 5)
    pygame.draw.rect(surf, (*frame_cols[1], A(255)), frame_rect,
                      border_top_left_radius=arch_r, border_top_right_radius=arch_r)
    pygame.draw.rect(surf, (*frame_cols[0], A(255)), frame_rect, width=2,
                      border_top_left_radius=arch_r, border_top_right_radius=arch_r)

    # --- ouverture interieure : sombre si fermee, lumineuse si ouverte ---
    inner_r = int(half * 0.85)
    inner_rect = (cx - half, top, w, h)
    if open_amount > 0.02:
        inner_col = (*glow_col, A(90 + open_amount * 130))
    else:
        inner_col = (16, 12, 10, A(230))
    pygame.draw.rect(surf, inner_col, inner_rect,
                      border_top_left_radius=inner_r, border_top_right_radius=inner_r)

    # rayons de lumiere qui s'echappent de l'embrasure quand elle est ouverte
    if open_amount > 0.05:
        n_ray = 5
        for i in range(n_ray):
            a = -math.pi / 2 + (i / (n_ray - 1) - 0.5) * 1.3
            length = (h * 0.55) * open_amount
            rx = cx + math.cos(a) * length
            ry = (top + h * 0.15) + math.sin(a) * length
            ray_col = (*glow_col, A(60 * open_amount))
            pygame.draw.line(surf, ray_col, (cx, top + h * 0.15), (rx, ry), 3)

    # --- deux battants qui pivotent vers les montants en s'ouvrant ---
    leaf_h = h - 6
    leaf_full_w = half - 2
    leaf_w = max(1.5, leaf_full_w * (1.0 - open_amount * 0.9))
    panel_col = frame_cols[0]
    panel_edge = frame_cols[2] if len(frame_cols) > 2 else frame_cols[1]
    for side in (-1, 1):
        hinge_x = cx + side * (half - 1)
        if side < 0:
            leaf_rect = (hinge_x, top + 3, leaf_w, leaf_h)
        else:
            leaf_rect = (hinge_x - leaf_w, top + 3, leaf_w, leaf_h)
        pygame.draw.rect(surf, (*panel_col, A(255)), leaf_rect)
        pygame.draw.rect(surf, (*panel_edge, A(220)), leaf_rect, width=1)
        # lattes horizontales du battant, pour lire une vraie porte
        lx, ly, lw, lh = leaf_rect
        if lw > 3:
            for j in range(1, 3):
                yy = ly + lh * j / 3.0
                pygame.draw.line(surf, (*panel_edge, A(160)), (lx + 1, yy), (lx + lw - 1, yy), 1)
            # poignee
            handle_x = hinge_x - side * min(lw - 2, leaf_full_w * 0.18)
            pygame.draw.circle(surf, (*glow_col, A(230)), (int(handle_x), int(sy + oy)), 2)

    # --- lianes / feuilles assorties au theme du stade en cours ---
    _draw_door_vines(surf, cx, top, half, bot, vine_cols, seed=(0.0 if kind == "in" else 13.0))

    screen.blit(surf, (sx - size / 2, sy - size / 2))


def draw_power_icon(surf, cx, cy, r, pid, ink=(35, 30, 25)):
    """Dessine un petit pictogramme qui evoque directement l'effet du pouvoir
    (eclair = vitesse, bouclier = protection, coeur = soin, ...), pour qu'on
    puisse deviner ce que fait un pouvoir rien qu'en regardant son dessin
    dans l'inventaire, sans avoir a lire son nom."""
    s = r / 10.0
    W = (255, 255, 255)

    if pid == "superforce":
        pygame.draw.line(surf, W, (cx - 6 * s, cy), (cx + 6 * s, cy), max(2, int(2.6 * s)))
        for dxs in (-6, 6):
            pygame.draw.rect(surf, W, (cx + dxs * s - 2 * s, cy - 4.5 * s, 4 * s, 9 * s),
                              border_radius=max(1, int(1.6 * s)))

    elif pid == "invisible":
        # silhouette de fantome (tete arrondie + bas ondule + yeux),
        # pour correspondre au 👻 utilise pour ce pouvoir dans la version HTML.
        pygame.draw.circle(surf, W, (int(cx), int(cy - 1 * s)), int(7 * s))
        pygame.draw.rect(surf, W, (cx - 7 * s, cy - 1 * s, 14 * s, 8 * s))
        for wx in (-5.5, -1.8, 1.8, 5.5):
            pygame.draw.circle(surf, W, (int(cx + wx * s), int(cy + 7 * s)), int(1.9 * s))
        for ex in (-2.6, 2.6):
            pygame.draw.circle(surf, ink, (int(cx + ex * s), int(cy - 2 * s)), max(1, int(1.3 * s)))

    elif pid == "permute":
        pygame.draw.arc(surf, W, (cx - 7 * s, cy - 7 * s, 14 * s, 14 * s), 0.3, math.pi, max(2, int(2 * s)))
        pygame.draw.arc(surf, W, (cx - 7 * s, cy - 7 * s, 14 * s, 14 * s), math.pi + 0.3, 2 * math.pi, max(2, int(2 * s)))
        pygame.draw.polygon(surf, W, [(cx + 7 * s, cy - 1 * s), (cx + 2.5 * s, cy - 3.5 * s), (cx + 3.5 * s, cy + 1 * s)])
        pygame.draw.polygon(surf, W, [(cx - 7 * s, cy + 1 * s), (cx - 2.5 * s, cy + 3.5 * s), (cx - 3.5 * s, cy - 1 * s)])

    elif pid == "vitesse":
        pts = [(cx + 1 * s, cy - 9 * s), (cx - 5 * s, cy + 1 * s), (cx - 1 * s, cy + 1 * s),
               (cx - 3 * s, cy + 9 * s), (cx + 5 * s, cy - 2 * s), (cx + 1 * s, cy - 2 * s)]
        pygame.draw.polygon(surf, W, pts)

    elif pid == "gel":
        for ang in (0, 60, 120):
            a = math.radians(ang)
            dx, dy = math.cos(a) * 8 * s, math.sin(a) * 8 * s
            pygame.draw.line(surf, W, (cx - dx, cy - dy), (cx + dx, cy + dy), max(1, int(1.6 * s)))
            bx, by = math.cos(a + math.pi / 2) * 2.2 * s, math.sin(a + math.pi / 2) * 2.2 * s
            for f in (0.55, -0.55):
                mx, my = dx * f, dy * f
                pygame.draw.line(surf, W, (cx + mx - bx, cy + my - by), (cx + mx + bx, cy + my + by),
                                  max(1, int(1.2 * s)))

    elif pid == "vision":
        rect = (cx - 9 * s, cy - 5.5 * s, 18 * s, 11 * s)
        pygame.draw.ellipse(surf, W, rect, max(2, int(1.8 * s)))
        pygame.draw.circle(surf, W, (int(cx), int(cy)), max(1, int(3 * s)))

    elif pid == "radar":
        pygame.draw.circle(surf, W, (int(cx), int(cy)), int(8 * s), max(1, int(1.4 * s)))
        pygame.draw.circle(surf, W, (int(cx), int(cy)), int(4.5 * s), max(1, int(1.2 * s)))
        pygame.draw.polygon(surf, W, [(cx, cy), (cx + 8 * s, cy), (cx + 6 * s, cy - 5 * s)])
        pygame.draw.circle(surf, W, (int(cx), int(cy)), max(1, int(1.2 * s)))

    elif pid == "bouclier":
        pts = [(cx, cy - 9 * s), (cx + 7 * s, cy - 6 * s), (cx + 7 * s, cy + 1 * s),
               (cx, cy + 9 * s), (cx - 7 * s, cy + 1 * s), (cx - 7 * s, cy - 6 * s)]
        pygame.draw.polygon(surf, W, pts, max(2, int(1.8 * s)))
        pygame.draw.line(surf, W, (cx, cy - 6 * s), (cx, cy + 6 * s), max(1, int(1.4 * s)))

    elif pid == "peur":
        # visage qui hurle de peur : yeux exorbites + sourcils releves + bouche
        # grande ouverte, pour correspondre au 😱 utilise dans la version HTML.
        pygame.draw.circle(surf, W, (int(cx), int(cy)), int(8 * s))
        for exs in (-3.2, 3.2):
            pygame.draw.circle(surf, ink, (int(cx + exs * s), int(cy - 2.2 * s)), max(1, int(2.1 * s)))
            pygame.draw.circle(surf, W, (int(cx + exs * s - 0.6 * s), int(cy - 2.7 * s)), max(1, int(0.6 * s)))
        pygame.draw.ellipse(surf, ink, (cx - 2.6 * s, cy + 1.2 * s, 5.2 * s, 4.4 * s))
        pygame.draw.line(surf, ink, (cx - 5.5 * s, cy - 6 * s), (cx - 2 * s, cy - 4.4 * s), max(1, int(1.3 * s)))
        pygame.draw.line(surf, ink, (cx + 5.5 * s, cy - 6 * s), (cx + 2 * s, cy - 4.4 * s), max(1, int(1.3 * s)))

    elif pid == "ralenti":
        pygame.draw.polygon(surf, W, [(cx - 6 * s, cy - 8 * s), (cx + 6 * s, cy - 8 * s), (cx, cy)],
                             max(1, int(1.6 * s)))
        pygame.draw.polygon(surf, W, [(cx - 6 * s, cy + 8 * s), (cx + 6 * s, cy + 8 * s), (cx, cy)],
                             max(1, int(1.6 * s)))
        pygame.draw.line(surf, W, (cx - 6 * s, cy - 8 * s), (cx + 6 * s, cy - 8 * s), max(1, int(1.6 * s)))
        pygame.draw.line(surf, W, (cx - 6 * s, cy + 8 * s), (cx + 6 * s, cy + 8 * s), max(1, int(1.6 * s)))

    elif pid == "leurre":
        pygame.draw.ellipse(surf, W, (cx - 8 * s, cy - 6 * s, 16 * s, 12 * s), max(2, int(1.8 * s)))
        pygame.draw.ellipse(surf, W, (cx - 5 * s, cy - 2 * s, 3.5 * s, 2.4 * s))
        pygame.draw.ellipse(surf, W, (cx + 1.5 * s, cy - 2 * s, 3.5 * s, 2.4 * s))
        pygame.draw.arc(surf, W, (cx - 4 * s, cy + 1 * s, 8 * s, 5 * s), math.pi, 2 * math.pi, max(1, int(1.4 * s)))

    elif pid == "teleport":
        for rr in (8, 5.5, 3):
            pygame.draw.ellipse(surf, W, (cx - rr * s, cy - rr * 0.7 * s, rr * 2 * s, rr * 1.4 * s),
                                 max(1, int(1.4 * s)))

    elif pid == "phase":
        n = 10
        for i in range(n):
            a0 = (2 * math.pi / n) * i
            a1 = a0 + (2 * math.pi / n) * 0.55
            pygame.draw.arc(surf, W, (cx - 8 * s, cy - 8 * s, 16 * s, 16 * s), a0, a1, max(2, int(2 * s)))

    elif pid == "rapetisse":
        for ang in (45, 135, 225, 315):
            a = math.radians(ang)
            ex, ey = math.cos(a) * 8 * s, math.sin(a) * 8 * s
            ix, iy = math.cos(a) * 3 * s, math.sin(a) * 3 * s
            pygame.draw.line(surf, W, (ex + cx, ey + cy), (ix + cx, iy + cy), max(1, int(1.6 * s)))
            pygame.draw.polygon(surf, W, [
                (ix + cx, iy + cy),
                (ix + cx + math.cos(a + 2.5) * 2.6 * s, iy + cy + math.sin(a + 2.5) * 2.6 * s),
                (ix + cx + math.cos(a - 2.5) * 2.6 * s, iy + cy + math.sin(a - 2.5) * 2.6 * s),
            ])

    elif pid == "dimension":
        # petit portail tourbillonnant (arcs en spirale) avec une etincelle
        # au centre, pour evoquer le passage vers une autre dimension.
        n = 3
        for i in range(n):
            rr = 9 * s - i * 2.6 * s
            a0 = i * 1.7
            pygame.draw.arc(surf, W, (cx - rr, cy - rr, rr * 2, rr * 2), a0, a0 + 4.6, max(1, int(1.5 * s)))
        pygame.draw.circle(surf, W, (int(cx), int(cy)), max(1, int(1.6 * s)))

    elif pid == "doublepas":
        for off in (-3.2, 3.2):
            pygame.draw.polygon(surf, W, [
                (cx - 5 * s + off * s, cy - 6 * s), (cx + 2 * s + off * s, cy), (cx - 5 * s + off * s, cy + 6 * s)
            ], max(2, int(1.8 * s)))

    elif pid == "soin":
        pygame.draw.circle(surf, W, (int(cx - 3.4 * s), int(cy - 2 * s)), int(4.2 * s))
        pygame.draw.circle(surf, W, (int(cx + 3.4 * s), int(cy - 2 * s)), int(4.2 * s))
        pygame.draw.polygon(surf, W, [(cx - 7.2 * s, cy - 1 * s), (cx + 7.2 * s, cy - 1 * s), (cx, cy + 8.5 * s)])

    elif pid == "confusion":
        pygame.draw.arc(surf, W, (cx - 8 * s, cy - 8 * s, 16 * s, 16 * s), 0.2, 4.5, max(2, int(1.8 * s)))
        pygame.draw.arc(surf, W, (cx - 4.5 * s, cy - 4.5 * s, 9 * s, 9 * s), 1.0, 5.5, max(2, int(1.6 * s)))

    elif pid == "aimant":
        pygame.draw.arc(surf, W, (cx - 6 * s, cy - 7 * s, 12 * s, 14 * s), 0, math.pi, max(2, int(2.4 * s)))
        for dxs in (-6, 6):
            pygame.draw.rect(surf, W, (cx + dxs * s - 1.8 * s, cy, 3.6 * s, 5.5 * s))
        pygame.draw.rect(surf, (200, 60, 60), (cx - 6 * s - 1.8 * s, cy + 3.5 * s, 3.6 * s, 2 * s))
        pygame.draw.rect(surf, (60, 90, 200), (cx + 6 * s - 1.8 * s, cy + 3.5 * s, 3.6 * s, 2 * s))

    elif pid == "invincible":
        pts = []
        for i in range(10):
            a = -math.pi / 2 + i * math.pi / 5
            rad = 8 * s if i % 2 == 0 else 3.4 * s
            pts.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad))
        pygame.draw.polygon(surf, W, pts)

    elif pid == "explosion":
        pts = []
        for i in range(12):
            a = i * math.pi / 6
            rad = 9 * s if i % 2 == 0 else 4 * s
            pts.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad))
        pygame.draw.polygon(surf, W, pts)

    elif pid == "clone":
        pygame.draw.circle(surf, W, (int(cx - 3 * s), int(cy - 2 * s)), int(5.5 * s), max(1, int(1.6 * s)))
        pygame.draw.circle(surf, W, (int(cx + 3 * s), int(cy + 1 * s)), int(5.5 * s))

    elif pid == "mirror":
        # petit miroir a main : cadre ovale + reflet diagonal + poignee
        pygame.draw.ellipse(surf, W, (cx - 5.5 * s, cy - 8.5 * s, 11 * s, 15 * s), max(2, int(1.6 * s)))
        pygame.draw.line(surf, W, (cx - 2.6 * s, cy - 5.5 * s), (cx + 1.8 * s, cy + 3.5 * s), max(1, int(1.3 * s)))
        pygame.draw.line(surf, W, (cx, cy + 6.8 * s), (cx, cy + 9.5 * s), max(1, int(1.8 * s)))

    elif pid == "rembobinage":
        # fleche circulaire vers l'arriere (undo)
        pygame.draw.arc(surf, W, (cx - 7 * s, cy - 7 * s, 14 * s, 14 * s), 0.6, math.pi * 1.7, max(2, int(2 * s)))
        pygame.draw.polygon(surf, W, [(cx - 7 * s, cy - 2 * s), (cx - 3 * s, cy - 4 * s), (cx - 3 * s, cy + 1 * s)])

    elif pid == "piege_pics":
        for dxs in (-4.5, 0, 4.5):
            pygame.draw.polygon(surf, W, [(cx + dxs * s, cy - 8 * s), (cx + dxs * s - 2.4 * s, cy + 4 * s),
                                           (cx + dxs * s + 2.4 * s, cy + 4 * s)])
        pygame.draw.line(surf, W, (cx - 8 * s, cy + 5 * s), (cx + 8 * s, cy + 5 * s), max(1, int(1.6 * s)))

    elif pid == "architecte":
        pygame.draw.rect(surf, W, (cx - 7 * s, cy - 2 * s, 6 * s, 5 * s))
        pygame.draw.rect(surf, W, (cx + 1 * s, cy - 2 * s, 6 * s, 5 * s))
        pygame.draw.rect(surf, W, (cx - 3.5 * s, cy - 7 * s, 7 * s, 5 * s))

    elif pid == "vampirisme":
        pygame.draw.polygon(surf, W, [(cx, cy + 7 * s), (cx - 7 * s, cy - 1 * s),
                                       (cx - 3.5 * s, cy - 7 * s), (cx, cy - 3 * s),
                                       (cx + 3.5 * s, cy - 7 * s), (cx + 7 * s, cy - 1 * s)])
        for dxs in (-2.2, 2.2):
            pygame.draw.polygon(surf, (170, 30, 50), [(cx + dxs * s, cy - 1 * s), (cx + dxs * s - 1.3 * s, cy + 3 * s),
                                                       (cx + dxs * s + 1.3 * s, cy + 3 * s)])

    else:
        pygame.draw.circle(surf, W, (int(cx), int(cy)), int(4 * s))


def draw_power_orb(sx, sy, d, t):
    pulse = 1 + math.sin(t * 4.2) * 0.12
    r = CELL * 0.30 * pulse
    glow = pygame.Surface((int(r * 4), int(r * 4)), pygame.SRCALPHA)
    pygame.draw.circle(glow, (255, 255, 255, 90), (int(r * 2), int(r * 2)), int(r * 1.9))
    screen.blit(glow, (sx - r * 2, sy - r * 2))
    pygame.draw.circle(screen, d["color"], (int(sx), int(sy)), int(r))
    pygame.draw.circle(screen, (255, 255, 255), (int(sx), int(sy)), int(r), width=2)
    draw_power_icon(screen, sx, sy, r, d["id"])


def draw_treasure_marker(sx, sy, t):
    """Petit coffre dore discret : le tresor optionnel du niveau, a trouver
    en plus de la sortie, sans aucune obligation."""
    pulse = 1 + math.sin(t * 3.0) * 0.08
    r = CELL * 0.26 * pulse
    glow = pygame.Surface((int(r * 4), int(r * 4)), pygame.SRCALPHA)
    pygame.draw.circle(glow, (255, 215, 0, 70), (int(r * 2), int(r * 2)), int(r * 1.8))
    screen.blit(glow, (sx - r * 2, sy - r * 2))
    w, h = r * 1.8, r * 1.3
    top = sy - h / 2 + r * 0.2
    rect = pygame.Rect(sx - w / 2, top, w, h)
    pygame.draw.rect(screen, (139, 94, 24), rect, border_radius=3)
    pygame.draw.rect(screen, (255, 215, 0), rect, width=2, border_radius=3)
    pygame.draw.line(screen, (255, 215, 0), (sx - w / 2, top + h * 0.35), (sx + w / 2, top + h * 0.35), 2)
    sparkle = 0.5 + 0.5 * math.sin(t * 6.0)
    pygame.draw.circle(screen, (255, 255, 255), (int(sx + w * 0.3), int(top - 4)), max(1, int(2 * sparkle)))


def draw_bonus_chest_marker(sx, sy, t):
    """Coffre bonus rare : plus gros, plus lumineux et plus anime que le
    tresor, pour bien marquer qu'il s'agit d'un evenement exceptionnel."""
    pulse = 1 + math.sin(t * 4.5) * 0.14
    r = CELL * 0.33 * pulse
    glow = pygame.Surface((int(r * 5), int(r * 5)), pygame.SRCALPHA)
    hue = (math.sin(t * 2.2) + 1) / 2
    pygame.draw.circle(glow, (255, int(180 + 60 * hue), 40, 100), (int(r * 2.5), int(r * 2.5)), int(r * 2.2))
    screen.blit(glow, (sx - r * 2.5, sy - r * 2.5))
    w, h = r * 2.0, r * 1.5
    top = sy - h / 2 + r * 0.2
    rect = pygame.Rect(sx - w / 2, top, w, h)
    pygame.draw.rect(screen, (120, 70, 20), rect, border_radius=4)
    pygame.draw.rect(screen, (255, 223, 90), rect, width=2, border_radius=4)
    pygame.draw.line(screen, (255, 223, 90), (sx - w / 2, top + h * 0.4), (sx + w / 2, top + h * 0.4), 2)
    pygame.draw.circle(screen, (255, 244, 200), (int(sx), int(top)), max(2, int(r * 0.22)))
    for i in range(3):
        ang = t * 2.5 + i * (math.tau / 3)
        px = sx + math.cos(ang) * r * 1.6
        py = sy - h * 0.3 + math.sin(ang) * r * 1.6
        a = 0.4 + 0.6 * math.sin(t * 5 + i)
        pygame.draw.circle(screen, (255, 255, 255), (int(px), int(py)), max(1, int(2 * a)))


def draw_explosion_fire(sx, sy, age, t):
    """Courte animation de flammes qui jaillissent du sol a l'endroit d'une
    explosion (pouvoir Explosion), en plus des etincelles deja generees par
    spawn_burst et de la trace de brulure laissee au sol (voir S.scorch_marks)."""
    fade = max(0.0, 1.0 - age / 1.0)
    if fade <= 0:
        return
    glow_r = CELL * 0.5 * fade
    glow = pygame.Surface((int(glow_r * 2.4), int(glow_r * 2.4)), pygame.SRCALPHA)
    gc = glow.get_width() / 2
    pygame.draw.circle(glow, (255, 120, 40, int(90 * fade)), (int(gc), int(gc)), int(glow_r))
    screen.blit(glow, (sx - gc, sy - gc))
    n = 6
    base_y = sy + CELL * 0.14
    for i in range(n):
        seed = i * 1.7
        lean = math.sin(t * 9 + seed) * CELL * 0.05
        height = (CELL * 0.42 + CELL * 0.16 * math.sin(t * 7 + seed)) * fade
        base_x = sx + math.cos(seed) * CELL * 0.22
        tip_x = base_x + lean
        tip_y = base_y - height
        w = CELL * 0.07
        col = FIRE_COLORS[i % len(FIRE_COLORS)]
        pygame.draw.polygon(screen, (*col, int(230 * fade)),
                             [(base_x - w, base_y), (base_x + w, base_y), (tip_x, tip_y)])


def draw_vampire_bat(bx, by, t, orbiting):
    """Chauve-souris du pouvoir Vampirisme : tourne autour du joueur tant
    qu'aucun monstre n'est a portee, ou fonce droit sur sa cible sinon (voir
    update_vampire_bat pour la logique de deplacement)."""
    if orbiting:
        ang = t * 5.5
        bx = bx + math.cos(ang) * CELL * 0.55
        by = by + math.sin(ang) * CELL * 0.33 - CELL * 0.25
    wing = 1.0 + math.sin(t * 22) * 0.5
    col = (25, 18, 26)
    for side in (-1, 1):
        wx = bx + side * CELL * 0.16 * wing
        wy = by - CELL * 0.03
        pygame.draw.polygon(screen, col, [(bx, by), (wx, wy), (bx + side * CELL * 0.06, by + CELL * 0.05)])
    pygame.draw.circle(screen, col, (int(bx), int(by)), max(2, int(CELL * 0.09)))
    pygame.draw.circle(screen, (220, 30, 40), (int(bx - 2), int(by - 1)), 1)
    pygame.draw.circle(screen, (220, 30, 40), (int(bx + 2), int(by - 1)), 1)


def draw_decoy(sx, sy, t):
    """Clone-leurre : une copie translucide du joueur (pouvoirs Leurre et
    Clone Leurre), pour vraiment tromper le monstre en lui faisant croire
    qu'il s'agit de l'original. Ne disparait que si un monstre le touche
    (voir check_decoy_touch), plus aucune limite de temps."""
    pulse = 1 + math.sin(t * 3.0) * 0.05
    r = CELL * 0.7 * pulse
    glow = pygame.Surface((int(r * 2.4), int(r * 2.4)), pygame.SRCALPHA)
    gc = glow.get_width() / 2
    pygame.draw.circle(glow, (230, 120, 190, 55), (int(gc), int(gc)), int(r))
    screen.blit(glow, (sx - gc, sy - gc))
    draw_player(sx, sy, "down", 0.0, True)


def draw_mirror(sx, sy, t, mirror):
    """Dessine le miroir a main pose au sol : cadre + surface reflechissante,
    qui s'allume d'une lumiere blanche pendant qu'il absorbe le monstre,
    reste doucement lumineux tant qu'il le retient prisonnier, puis
    s'estompe et disparait juste apres l'avoir relache."""
    state = mirror["state"]
    since = t - mirror["state_since"]

    # le miroir lui-meme se dissipe seulement a la toute fin de son cycle
    if state == "releasing":
        alpha = max(0, 255 - int(255 * min(1.0, since / MIRROR_RELEASE_DURATION)))
    else:
        alpha = 255

    # intensite de la lumiere blanche qu'il emet (c'est bien LUI qui brille,
    # pas le monstre)
    if state == "absorbing":
        glow_strength = min(1.0, since / MIRROR_ABSORB_DURATION)
    elif state == "holding":
        glow_strength = 0.55 + 0.25 * math.sin(t * 2.4)
    elif state == "releasing":
        glow_strength = max(0.0, 1.0 - since / MIRROR_RELEASE_DURATION) * 0.7
    else:
        glow_strength = 0.0

    w, h = CELL * 0.40, CELL * 0.72
    surf_size = int(max(w, h) * 3.4)
    surf = pygame.Surface((surf_size, surf_size), pygame.SRCALPHA)
    ccx = ccy = surf_size / 2

    if glow_strength > 0.02:
        _radial_glow(surf, (ccx, ccy), max(w, h) * (0.85 + glow_strength * 1.0),
                     (255, 255, 255), int(215 * glow_strength), steps=7)

    frame_col = (150, 148, 160, alpha)
    glass_col = (223, 233, 244, min(alpha, 235))
    frame_rect = (ccx - w / 2 - 4, ccy - h / 2 - 4, w + 8, h + 8)
    glass_rect = (ccx - w / 2, ccy - h / 2, w, h)

    pygame.draw.ellipse(surf, frame_col, frame_rect)
    pygame.draw.ellipse(surf, glass_col, glass_rect)
    # reflet diagonal, pour bien lire une surface de verre/miroir
    pygame.draw.line(surf, (255, 255, 255, min(alpha, 210)),
                      (ccx - w * 0.22, ccy - h * 0.32), (ccx + w * 0.06, ccy + h * 0.18),
                      max(1, int(CELL * 0.035)))
    pygame.draw.ellipse(surf, (90, 88, 98, alpha), frame_rect, width=max(1, int(CELL * 0.025)))
    # petit pied/socle pour qu'il tienne debout au sol
    pygame.draw.rect(surf, (90, 88, 98, alpha), (ccx - w * 0.12, ccy + h / 2, w * 0.24, max(3, CELL * 0.05)))

    screen.blit(surf, (sx - ccx, sy - ccy))


def _rot(px, py, ang):
    ca, sa = math.cos(ang), math.sin(ang)
    return px * ca - py * sa, px * sa + py * ca


MONSTER_ENERGY_COLORS = {
    0: (120, 200, 255),
    1: (140, 220, 160),
    2: (230, 200, 90),
    3: (255, 130, 60),
    4: (230, 40, 40),
}


def draw_monster_energy(sx, sy, tier, t):
    """Dans l'autre dimension, on ne voit plus le corps du monstre mais
    l'energie continue qu'il degage : plus son niveau (tier) est eleve,
    plus l'aura est vaste, intense et terrifiante."""
    color = MONSTER_ENERGY_COLORS.get(tier, MONSTER_ENERGY_COLORS[4])
    base_r = CELL * (0.34 + tier * 0.11)
    pulse = 0.85 + 0.15 * math.sin(t * (2.5 + tier * 0.8))
    r = base_r * pulse
    size = int(r * 5) + 2
    glow = pygame.Surface((size, size), pygame.SRCALPHA)
    gc = size // 2
    _radial_glow(glow, (gc, gc), r * 2.2, color, 90 + tier * 25, steps=8)
    _radial_glow(glow, (gc, gc), r * 1.1, color, 150 + tier * 20, steps=6)
    screen.blit(glow, (sx - gc, sy - gc))
    pygame.draw.circle(screen, color, (int(sx), int(sy)), max(2, int(r * 0.45)))
    pygame.draw.circle(screen, (255, 255, 255), (int(sx), int(sy)), max(1, int(r * 0.15)))
    n_arcs = 3 + tier
    for i in range(n_arcs):
        a = (i / n_arcs) * math.tau + t * (1.5 + tier * 0.3)
        rr = r * (1.3 + 0.2 * math.sin(t * 4 + i))
        x2, y2 = sx + math.cos(a) * rr, sy + math.sin(a) * rr
        pygame.draw.line(screen, color, (int(sx), int(sy)), (int(x2), int(y2)), 1)


def draw_monster(sx, sy, tier, since, t, frozen, spooky=False, mirror_state=None, mirror_since=0.0,
                  drain_prog=0.0, shrunk=False):
    """Dessine une vraie petite créature (silhouette différente par palier),
    qui grandit et devient de plus en plus effrayante a chaque niveau :
    petite et fluette au debut, elle enfle et se fait plus menacante avec le
    temps (taille, aura sombre, regard de plus en plus intense). Sur un
    stade plonge dans le noir (spooky), son regard devient nettement plus
    inquietant : un rouge plus vif et plus saturé, qui pulse doucement,
    au lieu du regard normal en plein jour.

    mirror_state/mirror_since decrivent le cycle du pouvoir Miroir Piegeur :
    "absorbing" -> le monstre se debat en se retrecissant et en s'effacant
    progressivement (aspire dans le miroir) ; "holding" -> entierement
    retenu prisonnier, donc invisible ; "releasing" -> il vient de resortir
    et tremble de rage (flash rouge + cri) pendant un court instant."""
    if mirror_state == "holding":
        return  # completement absorbe et retenu dans le miroir : invisible pour l'instant

    capture_scale = 1.0
    capture_alpha_mult = 1.0
    jitter_x = jitter_y = 0.0
    anger_prog = None
    if mirror_state == "absorbing":
        prog = min(1.0, mirror_since / MIRROR_ABSORB_DURATION)
        capture_scale = max(0.05, 1.0 - prog * 0.92)
        capture_alpha_mult = max(0.0, 1.0 - prog * 0.85)
        # le monstre se debat de plus en plus fort a mesure qu'il est aspire
        shake = 2.4 * (0.3 + prog * 1.6)
        jitter_x = math.sin(t * 42.0) * shake
        jitter_y = math.cos(t * 35.0) * shake * 0.6
    elif mirror_state == "releasing":
        anger_prog = min(1.0, mirror_since / MIRROR_RELEASE_DURATION)
        shake = 5.0 * (1.0 - anger_prog)
        jitter_x = math.sin(t * 55.0) * shake
        jitter_y = math.cos(t * 47.0) * shake * 0.5
    elif drain_prog > 0:
        # Vampirisme : le monstre mordu se recroqueville et s'efface peu a
        # peu, comme vide de sa substance, avec un leger tremblement.
        capture_scale = max(0.15, 1.0 - drain_prog * 0.82)
        capture_alpha_mult = max(0.0, 1.0 - drain_prog * 0.92)
        shake = 1.8 * (1.0 - drain_prog * 0.4)
        jitter_x = math.sin(t * 20.0) * shake
        jitter_y = math.cos(t * 17.0) * shake * 0.5

    sx = sx + jitter_x
    sy = sy + jitter_y

    bob = math.sin(t * 4.5) * 3

    growth = max(0, since)           # 0 au niveau ou le monstre apparait, augmente ensuite a chaque niveau
    shrink_mult = 0.55 if shrunk else 1.0   # Rapetissement : le monstre visible retrecit nettement
    scale = min(2.6, 0.72 + growth * 0.085) * capture_scale * shrink_mult   # petit/mince -> enorme
    fear = min(1.0, growth / 14.0)   # 0 -> 1 : intensite de l'aura/du regard, monte plus lentement que la taille

    sy = sy + bob * scale
    s = (CELL / 34.0) * scale
    size = int(CELL * 2.6 * scale) + 30
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    cx, cy = size / 2, size / 2
    body = MONSTER_TIER_COLORS[min(tier, 4)]
    if frozen:
        body = tuple(min(255, c + 70) for c in body)
    elif drain_prog > 0:
        vr = (150, 10, 30)
        body = tuple(int(c * (1 - drain_prog) + v * drain_prog) for c, v in zip(body, vr))
    dark = tuple(max(0, c - 60) for c in body)
    underwater = getattr(S, "wall_theme", "pierre") == "eau"
    if frozen:
        eye_glow = (150, 230, 255)
        eye_r_mult = 1.0
    elif drain_prog > 0:
        pulse = 0.6 + 0.4 * math.sin(t * 8.0)
        eye_glow = (int(120 * pulse), 0, 0)
        eye_r_mult = max(0.4, 1.0 - drain_prog * 0.6)
    elif spooky:
        pulse = 0.75 + 0.25 * math.sin(t * 6.0 + sx * 0.02)
        eye_glow = (255, int(20 * pulse), int(20 * pulse))
        eye_r_mult = 1.35 + 0.25 * pulse
    elif underwater:
        pulse = 0.75 + 0.25 * math.sin(t * 5.0 + sx * 0.02)
        eye_glow = (max(0, int(90 - 40 * fear)), int(220 * pulse), 255)
        eye_r_mult = 1.0
    else:
        eye_glow = (255, max(0, int(60 - 55 * fear)), max(0, int(60 - 55 * fear)))
        eye_r_mult = 1.0

    # aura sombre et rougeoyante qui s'intensifie a mesure que le monstre grandit
    if fear > 0.02 and not frozen:
        glow_r = int((15 + 16 * fear) * s)
        pygame.draw.circle(surf, (180, 10, 10, int(95 * fear)), (int(cx), int(cy - 2 * s)), glow_r)

    # ombre au sol (douce, degradee)
    _draw_soft_ellipse_shadow(surf, (cx, cy + 12.5 * s), 11 * s, 3.5 * s, max_alpha=100)

    if underwater and not frozen:
        # petit sillage d'ondulation cyan + nageoire dorsale, pour l'allure aquatique
        ripple_r = (12 + 3 * math.sin(t * 3.0)) * s
        pygame.draw.ellipse(surf, (120, 220, 255, 55), (cx - ripple_r, cy - ripple_r * 0.6, ripple_r * 2, ripple_r * 1.2), width=max(1, int(1.2 * s)))
        pygame.draw.polygon(surf, dark, [(cx - 1.5 * s, cy - 10 * s), (cx, cy - 17 * s), (cx + 1.5 * s, cy - 10 * s)])

    if tier == 0:
        # petit lezard trapu : corps ovale + queue + oreilles pointues
        pygame.draw.line(surf, dark, (cx - 2 * s, cy + 6 * s), (cx - 12 * s, cy + 10 * s), max(2, int(3 * s)))
        pygame.draw.ellipse(surf, body, (cx - 11 * s, cy - 6 * s, 22 * s, 18 * s))
        pygame.draw.polygon(surf, dark, [(cx - 6 * s, cy - 6 * s), (cx - 9 * s, cy - 13 * s), (cx - 3 * s, cy - 6 * s)])
        pygame.draw.polygon(surf, dark, [(cx + 6 * s, cy - 6 * s), (cx + 9 * s, cy - 13 * s), (cx + 3 * s, cy - 6 * s)])
        eyes = [(-4 * s, -2 * s), (4 * s, -2 * s)]
    elif tier == 1:
        # gobelin : tete + oreilles larges + petit corps
        pygame.draw.ellipse(surf, body, (cx - 8 * s, cy - 2 * s, 16 * s, 14 * s))
        pygame.draw.circle(surf, body, (int(cx), int(cy - 8 * s)), int(9 * s))
        pygame.draw.polygon(surf, dark, [(cx - 8 * s, cy - 8 * s), (cx - 15 * s, cy - 4 * s), (cx - 6 * s, cy - 2 * s)])
        pygame.draw.polygon(surf, dark, [(cx + 8 * s, cy - 8 * s), (cx + 15 * s, cy - 4 * s), (cx + 6 * s, cy - 2 * s)])
        pygame.draw.polygon(surf, (255, 255, 255), [(cx - 3 * s, cy - 1 * s), (cx - 1 * s, cy - 1 * s), (cx - 2 * s, cy + 2 * s)])
        pygame.draw.polygon(surf, (255, 255, 255), [(cx + 3 * s, cy - 1 * s), (cx + 1 * s, cy - 1 * s), (cx + 2 * s, cy + 2 * s)])
        eyes = [(-4 * s, -9 * s), (4 * s, -9 * s)]
    elif tier == 2:
        # ogre : gros corps rond, petites cornes, defenses
        pygame.draw.circle(surf, body, (int(cx), int(cy)), int(13 * s))
        pygame.draw.polygon(surf, dark, [(cx - 5 * s, cy - 11 * s), (cx - 8 * s, cy - 16 * s), (cx - 2 * s, cy - 10 * s)])
        pygame.draw.polygon(surf, dark, [(cx + 5 * s, cy - 11 * s), (cx + 8 * s, cy - 16 * s), (cx + 2 * s, cy - 10 * s)])
        pygame.draw.polygon(surf, (255, 255, 255), [(cx - 5 * s, cy + 4 * s), (cx - 3 * s, cy + 4 * s), (cx - 4 * s, cy + 9 * s)])
        pygame.draw.polygon(surf, (255, 255, 255), [(cx + 5 * s, cy + 4 * s), (cx + 3 * s, cy + 4 * s), (cx + 4 * s, cy + 9 * s)])
        eyes = [(-5 * s, -3 * s), (5 * s, -3 * s)]
    elif tier == 3:
        # petit demon : corps + ailes triangulaires + cornes recourbees
        wingL = [(cx - 9 * s, cy - 2 * s), (cx - 20 * s, cy - 9 * s), (cx - 16 * s, cy + 4 * s), (cx - 8 * s, cy + 3 * s)]
        wingR = [(cx + 9 * s, cy - 2 * s), (cx + 20 * s, cy - 9 * s), (cx + 16 * s, cy + 4 * s), (cx + 8 * s, cy + 3 * s)]
        pygame.draw.polygon(surf, dark, wingL)
        pygame.draw.polygon(surf, dark, wingR)
        pygame.draw.circle(surf, body, (int(cx), int(cy)), int(11 * s))
        pygame.draw.polygon(surf, (40, 20, 10), [(cx - 6 * s, cy - 9 * s), (cx - 10 * s, cy - 15 * s), (cx - 3 * s, cy - 8 * s)])
        pygame.draw.polygon(surf, (40, 20, 10), [(cx + 6 * s, cy - 9 * s), (cx + 10 * s, cy - 15 * s), (cx + 3 * s, cy - 8 * s)])
        eyes = [(-4 * s, -2 * s), (4 * s, -2 * s)]
    else:
        # faucheur : capuche sombre + visage squelette
        pygame.draw.polygon(surf, dark, [(cx, cy - 16 * s), (cx - 12 * s, cy + 12 * s), (cx + 12 * s, cy + 12 * s)])
        pygame.draw.circle(surf, (225, 225, 220), (int(cx), int(cy - 1 * s)), int(8 * s))
        eyes = [(-3 * s, -1 * s), (3 * s, -1 * s)]
        for ex, ey in eyes:
            pygame.draw.circle(surf, (10, 10, 10), (int(cx + ex), int(cy + ey)), max(2, int(2.2 * s)))
            if spooky and not frozen:
                pygame.draw.circle(surf, eye_glow, (int(cx + ex), int(cy + ey)), max(1, int(1.1 * eye_r_mult * s)))
        eyes = []  # deja dessines

    for ex, ey in eyes:
        pygame.draw.circle(surf, (20, 20, 20), (int(cx + ex), int(cy + ey)), max(2, int(2 * s)))
        pygame.draw.circle(surf, eye_glow, (int(cx + ex), int(cy + ey)), max(1, int((1 + 0.8 * fear) * eye_r_mult * s)))

    if frozen:
        # bloc de glace qui enferme le monstre : coque translucide + eclats
        # pointus qui depassent sur les bords + reflet, pour bien donner
        # l'impression qu'il est prisonnier de la glace (et pas juste teinte).
        ice_w, ice_h = 15 * s + 11 * s, 15 * s + 15 * s
        ice_cx, ice_cy = cx, cy - 2 * s
        ice_rect = (ice_cx - ice_w / 2, ice_cy - ice_h / 2, ice_w, ice_h)
        casing = pygame.Surface((size, size), pygame.SRCALPHA)
        for ang in range(20, 360, 40):
            a = math.radians(ang)
            base_x = ice_cx + math.cos(a) * (ice_w / 2 - 1 * s)
            base_y = ice_cy + math.sin(a) * (ice_h / 2 - 1 * s)
            tip_x = ice_cx + math.cos(a) * (ice_w / 2 + 6 * s)
            tip_y = ice_cy + math.sin(a) * (ice_h / 2 + 6 * s)
            a1, a2 = a - 0.28, a + 0.28
            p1 = (ice_cx + math.cos(a1) * (ice_w / 2 - 2 * s), ice_cy + math.sin(a1) * (ice_h / 2 - 2 * s))
            p2 = (ice_cx + math.cos(a2) * (ice_w / 2 - 2 * s), ice_cy + math.sin(a2) * (ice_h / 2 - 2 * s))
            pygame.draw.polygon(casing, (215, 245, 255, 150), [p1, (tip_x, tip_y), p2])
        pygame.draw.ellipse(casing, (190, 235, 255, 120), ice_rect)
        pygame.draw.ellipse(casing, (255, 255, 255, 130), ice_rect, width=max(2, int(2 * s)))
        pygame.draw.ellipse(casing, (255, 255, 255, 140),
                             (ice_cx - ice_w * 0.32, ice_cy - ice_h * 0.38, ice_w * 0.28, ice_h * 0.2))
        for fx, fy in [(9 * s, -12 * s), (-10 * s, -10 * s), (7 * s, 8 * s)]:
            draw_text(casing, "*", FONT_SMALL, (255, 255, 255), ice_cx + fx, ice_cy + fy, center=True, shadow=False)
        surf.blit(casing, (0, 0))

    if anger_prog is not None:
        # sortie du miroir : flash rouge de colere qui s'attenue vite, plus
        # un petit cri ("!!") au-dessus de la tete pour bien montrer qu'il
        # est furieux d'avoir ete piege.
        flash_a = int(150 * (1.0 - anger_prog))
        if flash_a > 0:
            flash = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(flash, (255, 40, 30, flash_a), (int(cx), int(cy)), int(16 * s))
            surf.blit(flash, (0, 0))
            draw_text(surf, "!!", FONT_MED, (255, 60, 50), cx, cy - 20 * s, center=True, shadow=False)

    if capture_alpha_mult < 0.999:
        surf.set_alpha(max(0, int(255 * capture_alpha_mult)))

    screen.blit(surf, (sx - cx, sy - cy))


def _draw_soft_ellipse_shadow(surf, center, rx, ry, max_alpha=90, steps=5):
    """Ombre de contact douce et degradee (au lieu d'une simple ellipse plate
    et a bord net) : plusieurs ellipses de plus en plus petites et opaques,
    empilees, pour un rendu plus realiste au sol."""
    cx, cy = center
    for i in range(steps, 0, -1):
        frac = i / steps
        w = max(1, int(rx * 2 * frac))
        h = max(1, int(ry * 2 * frac))
        a = int(max_alpha * (1 - frac) ** 0.7)
        if a <= 0:
            continue
        pygame.draw.ellipse(surf, (0, 0, 0, a), (cx - w / 2, cy - h / 2, w, h))


def _radial_glow(surf, center, max_r, color_rgb, max_alpha, steps=7):
    """Approxime un degrade radial (non supporte nativement par pygame) en
    empilant des cercles de plus en plus petits et de plus en plus opaques :
    c'est ce qui donne l'effet de 'bulle transparente' / halo lumineux."""
    cx, cy = center
    for i in range(steps, 0, -1):
        r = max(1, int(max_r * i / steps))
        a = int(max_alpha * (1 - i / steps))
        if a <= 0:
            continue
        pygame.draw.circle(surf, (*color_rgb, a), (int(cx), int(cy)), r)


def _draw_realistic_head(surf, center, r, t, facing="down"):
    """Vraie petite tete humaine (peau ombree, cheveux, sourcils, yeux avec
    reflet et clignement occasionnel, nez, bouche, joues) plutot qu'un motif
    abstrait : couleurs chaudes et claires, faciles a lire meme en petit, et
    nettement distinctes du sol/des murs pour qu'on reconnaisse tout de
    suite un visage.

    La tete tourne vraiment pour regarder dans la direction du deplacement,
    comme dans un vrai jeu vu de dessus : face vue de face quand on regarde
    "down" (vers la camera/le bas de l'ecran), dos de la tete (cheveux)
    quand on regarde "up" (on s'eloigne de la camera), et vrai visage de
    profil (un seul oeil, nez qui depasse du cote regarde) quand on regarde
    "left" ou "right"."""
    cx, cy = center
    ri = max(1, int(r))

    skin = (233, 190, 154)
    skin_dark = (198, 150, 116)
    hair_col = (68, 44, 32)
    hair_dark = (46, 28, 20)

    # look_side : -1 = profil tourne vers la gauche, +1 = vers la droite,
    # 0 = pas de profil (face ou dos). show_face : faux quand on ne voit
    # que l'arriere du crane (facing == "up").
    look_side = -1.0 if facing == "left" else (1.0 if facing == "right" else 0.0)
    show_face = facing != "up"

    # --- peau, avec un ombrage doux (cote oppose a la lumiere/au regard)
    # pour donner du volume plutot qu'un disque plat uniforme ---
    pygame.draw.circle(surf, skin, (int(cx), int(cy)), ri)
    shade_side = -look_side if look_side else 1.0
    pygame.draw.circle(surf, (*skin_dark, 130),
                        (int(cx + shade_side * r * 0.32), int(cy + r * 0.10)), max(1, int(ri * 0.62)))
    pygame.draw.circle(surf, skin, (int(cx - shade_side * r * 0.14), int(cy - r * 0.08)), max(1, int(ri * 0.64)))

    # --- cheveux : calotte sur le haut du crane, avec quelques meches plus
    # sombres pour la texture. De dos (facing "up"), la calotte descend
    # beaucoup plus bas et couvre presque toute la tete puisqu'on ne voit
    # que l'arriere du crane. De profil, on garde une meche pleine du cote
    # opposé au regard (l'arriere de la tete) et une frange plus fine du
    # cote regarde (le front, degage pour laisser la place au visage). ---
    if not show_face:
        cap_cy = cy - r * 0.08
        cap_rect = (cx - r * 1.05, cap_cy - r * 1.02, r * 2.10, r * 1.85)
        pygame.draw.ellipse(surf, hair_col, cap_rect)
        for mx in (-0.5, -0.15, 0.2, 0.55):
            pygame.draw.line(surf, hair_dark, (cx + mx * r, cap_cy - r * 0.55),
                              (cx + mx * r * 1.15, cap_cy + r * 0.55), max(1, int(r * 0.06)))
        # nuque : petite ombre en bas pour bien lire l'arriere du cou
        pygame.draw.ellipse(surf, (*skin_dark, 150), (cx - r * 0.30, cy + r * 0.55, r * 0.60, r * 0.30))
        pygame.draw.circle(surf, (40, 26, 16, 220), (int(cx), int(cy)), ri, width=1)
        return

    cap_cy = cy - r * 0.58
    cap_front_shift = look_side * r * 0.22   # la calotte suit un peu le sens du regard
    cap_rect = (cx - r * 1.05 + cap_front_shift * 0.3, cap_cy - r * 0.55, r * 2.10, r * 1.10)
    pygame.draw.ellipse(surf, hair_col, cap_rect)
    for mx in (-0.5, -0.15, 0.2, 0.55):
        pygame.draw.line(surf, hair_dark, (cx + mx * r, cap_cy - r * 0.35),
                          (cx + mx * r * 1.15, cap_cy + r * 0.28), max(1, int(r * 0.06)))
    # petites meches sur les tempes : bien pleine a l'arriere de la tete
    # (cote oppose au regard), plus discrete cote visage en profil
    for side in (-1, 1):
        temple_w = r * 0.32
        if look_side and side == look_side:
            temple_w *= 0.35   # cote front/visage : degage
        pygame.draw.ellipse(surf, hair_col,
                             (cx + side * r * 0.92 - temple_w / 2, cy - r * 0.35, temple_w, r * 0.55))

    # --- sourcils : un seul, avance vers le cote regarde, quand de profil ---
    brow_sides = (look_side,) if look_side else (-1, 1)
    for side in brow_sides:
        bx = cx + side * r * (0.30 if not look_side else 0.46)
        by = cy - r * 0.14
        pygame.draw.line(surf, hair_dark, (bx - side * r * 0.14, by + r * 0.02),
                          (bx + side * r * 0.14, by - r * 0.03), max(1, int(r * 0.07)))

    # --- yeux : de face, les deux ; de profil, un seul (celui du cote
    # regarde, avance vers l'avant du visage) ; clignement occasionnel
    # (deterministe via t) pour un peu de vie ---
    blink = (t % 3.4) < 0.12
    eye_sides = (look_side,) if look_side else (-1, 1)
    for side in eye_sides:
        ex = cx + side * r * (0.30 if not look_side else 0.44)
        ey = cy + r * 0.02
        if blink:
            pygame.draw.line(surf, hair_dark, (ex - r * 0.11, ey), (ex + r * 0.11, ey), max(1, int(r * 0.05)))
        else:
            pygame.draw.ellipse(surf, (255, 255, 255), (ex - r * 0.13, ey - r * 0.09, r * 0.26, r * 0.18))
            pygame.draw.circle(surf, (90, 60, 42), (int(ex + side * r * 0.02), int(ey)), max(1, int(r * 0.075)))
            pygame.draw.circle(surf, (20, 14, 10), (int(ex + side * r * 0.02), int(ey)), max(1, int(r * 0.035)))
            pygame.draw.circle(surf, (255, 255, 255), (int(ex + side * r * 0.05 - 1), int(ey - r * 0.03)), 1)
        pygame.draw.line(surf, hair_dark, (ex - r * 0.14, ey + r * 0.11), (ex + r * 0.14, ey + r * 0.11), 1)

    # --- nez : de face, un simple trait d'ombre ; de profil, une vraie
    # petite arete qui depasse du contour du visage vers le cote regarde,
    # pour bien montrer que la tete est tournee ---
    if look_side:
        nx = cx + look_side * r * 0.62
        pygame.draw.polygon(surf, skin, [
            (cx + look_side * r * 0.40, cy - r * 0.02),
            (nx, cy + r * 0.10),
            (cx + look_side * r * 0.40, cy + r * 0.18),
        ])
        pygame.draw.line(surf, (*skin_dark, 200), (cx + look_side * r * 0.40, cy + r * 0.18), (nx, cy + r * 0.10), 1)
    else:
        pygame.draw.line(surf, (*skin_dark, 180), (cx, cy + r * 0.06), (cx - r * 0.05, cy + r * 0.22),
                          max(1, int(r * 0.06)))

    # --- joues : legere touche rosee pour la chaleur/le realisme (les deux
    # de face, seulement celle du cote visible en profil) ---
    cheek_sides = (look_side,) if look_side else (-1, 1)
    for side in cheek_sides:
        pygame.draw.circle(surf, (235, 130, 120, 55), (int(cx + side * r * 0.42), int(cy + r * 0.28)), max(1, int(r * 0.16)))

    # --- bouche : leger sourire, recentre vers le cote regarde en profil ---
    mouth_cx = cx + look_side * r * 0.18
    mouth_rect = (mouth_cx - r * 0.20, cy + r * 0.30, r * 0.40, r * 0.24)
    pygame.draw.arc(surf, (150, 78, 68), mouth_rect, math.pi * 1.08, math.pi * 1.92, max(1, int(r * 0.06)))

    # --- contour + reflet, pour bien detacher la tete du reste du corps ---
    pygame.draw.circle(surf, (40, 26, 16, 220), (int(cx), int(cy)), ri, width=1)
    pygame.draw.circle(surf, (255, 255, 255, 90), (int(cx - r * 0.36), int(cy - r * 0.40)), max(1, int(r * 0.14)))


def _draw_power_smoke_aura(surf, center, s, t):
    """Legere aura magique qui entoure le joueur des qu'il possede un
    pouvoir en reserve (meme non utilise), animee d'un leger mouvement
    continu : plusieurs volutes violettes/bleutees qui tournent lentement en
    ellipse autour de tout le corps (tete comprise), assez loin de lui pour
    ne jamais le recouvrir, avec un coeur plus clair pour bien la distinguer
    du sol et des murs (jamais gris/brun comme eux)."""
    cx, cy = center
    n = 7
    for i in range(n):
        seed = i * 1.87
        drift = ((t * 0.25) + seed * 0.41) % 1.0
        ang = seed * 1.9 + t * 0.35
        rx = (11.5 + 1.6 * math.sin(seed * 2.7)) * s   # hors de la largeur du corps
        ry = (13.5 + 1.6 * math.cos(seed * 1.9)) * s   # englobe la tete et les jambes
        px = cx + math.cos(ang) * rx
        py = cy + math.sin(ang) * ry - drift * 3 * s
        r = (2.1 + 1.2 * math.sin(t * 1.6 + seed)) * s
        alpha = int(80 * (1.0 - drift * 0.55))
        if alpha <= 2:
            continue
        pygame.draw.circle(surf, (146, 110, 230, alpha), (int(px), int(py)), max(1, int(r)))
        pygame.draw.circle(surf, (215, 195, 255, int(alpha * 0.75)), (int(px), int(py)), max(1, int(r * 0.45)))


def _draw_dimension_aura(surf, center, s, t):
    """Aura amplifiee et doree qui remplace la fumee magique habituelle
    quand on est dans l'autre dimension : memes volutes tournantes que
    _draw_power_smoke_aura, en plus grand et plus lumineux, plus des
    rayons qui irradient du corps. Dessinee AVANT le corps (comme la
    fumee de pouvoir), pour ne jamais le recouvrir ni le cacher."""
    cx, cy = center
    n_rays = 10
    for i in range(n_rays):
        a = (i / n_rays) * 2 * math.pi + t * 0.6
        length = (10 + 3 * math.sin(t * 2.2 + i)) * s
        x2 = cx + math.cos(a) * length
        y2 = cy + math.sin(a) * length
        alpha = int(70 + 40 * math.sin(t * 3 + i))
        pygame.draw.line(surf, (255, 221, 90, max(20, alpha)), (cx, cy), (x2, y2), max(1, int(1.1 * s)))
    _radial_glow(surf, (int(cx), int(cy)), 9 * s, (255, 232, 150), 130, steps=7)
    n = 9
    for i in range(n):
        seed = i * 1.87
        drift = ((t * 0.3) + seed * 0.41) % 1.0
        ang = seed * 1.9 + t * 0.5
        rx = (13.5 + 2.0 * math.sin(seed * 2.7)) * s
        ry = (15.5 + 2.0 * math.cos(seed * 1.9)) * s
        px = cx + math.cos(ang) * rx
        py = cy + math.sin(ang) * ry - drift * 3.5 * s
        r = (2.6 + 1.4 * math.sin(t * 1.8 + seed)) * s
        alpha = int(140 * (1.0 - drift * 0.5))
        if alpha <= 2:
            continue
        pygame.draw.circle(surf, (255, 205, 70, alpha), (int(px), int(py)), max(1, int(r)))
        pygame.draw.circle(surf, (255, 245, 200, int(alpha * 0.8)), (int(px), int(py)), max(1, int(r * 0.45)))


def _draw_vampire_vapor(surf, center, s, t):
    """Vapeur de sang, presque transparente, qui emane du corps pendant le
    pouvoir Vampirisme : de fines volutes rouge sombre qui montent
    lentement et se dissipent (alpha volontairement tres faible pour
    rester "presque transparente" comme demande). Dessinee AVANT le corps,
    comme les autres auras, pour ne jamais le recouvrir."""
    cx, cy = center
    n = 8
    for i in range(n):
        seed = i * 2.13
        drift = ((t * 0.6) + seed * 0.37) % 1.0
        ang = seed * 1.7 + t * 0.2
        rx = (7.5 + 1.8 * math.sin(seed * 2.1)) * s
        px = cx + math.cos(ang) * rx
        py = cy + 9 * s - drift * 14 * s
        r = (1.6 + 1.0 * math.sin(t * 1.4 + seed)) * s
        alpha = int(55 * (1.0 - drift))
        if alpha <= 2:
            continue
        pygame.draw.circle(surf, (120, 10, 24, alpha), (int(px), int(py)), max(1, int(r)))


def _draw_vampire_hood(surf, center, r, alpha):
    """Capuche de style Dracula posee sur la tete pendant le pouvoir
    Vampirisme : capuche noire avec un col releve en pointes de chaque
    cote, et deux crocs blancs bien visibles sous la tete."""
    hx, hy = center
    a = min(alpha, 235)
    hood_col = (18, 10, 22, a)
    hood_pts = [(hx - r * 1.15, hy + r * 0.35), (hx - r * 0.85, hy - r * 1.05),
                (hx, hy - r * 1.35), (hx + r * 0.85, hy - r * 1.05),
                (hx + r * 1.15, hy + r * 0.35), (hx + r * 0.65, hy - r * 0.15),
                (hx, hy - r * 0.35), (hx - r * 0.65, hy - r * 0.15)]
    pygame.draw.polygon(surf, hood_col, hood_pts)
    pygame.draw.polygon(surf, hood_col, [(hx - r * 1.15, hy + r * 0.35),
                                          (hx - r * 1.7, hy + r * 1.3),
                                          (hx - r * 0.55, hy + r * 0.55)])
    pygame.draw.polygon(surf, hood_col, [(hx + r * 1.15, hy + r * 0.35),
                                          (hx + r * 1.7, hy + r * 1.3),
                                          (hx + r * 0.55, hy + r * 0.55)])
    fang_w = r * 0.16
    fang_h = r * 0.38
    fy = hy + r * 0.5
    pygame.draw.polygon(surf, (250, 250, 245, a),
                         [(hx - r * 0.28, fy), (hx - r * 0.28 + fang_w, fy),
                          (hx - r * 0.28 + fang_w / 2, fy + fang_h)])
    pygame.draw.polygon(surf, (250, 250, 245, a),
                         [(hx + r * 0.28 - fang_w, fy), (hx + r * 0.28, fy),
                          (hx + r * 0.28 - fang_w / 2, fy + fang_h)])


def draw_player(sx, sy, facing, walk_phase, ghost, active=None, t=0.0, torch=False, has_power=False):
    """Dessine un vrai petit personnage (jambes, bras, torse, tete, cheveux)
    qui marche et regarde dans la direction du deplacement, plus les auras
    visuelles des pouvoirs actifs (bouclier, autre dimension, super force,
    vitesse, invincibilite, phasage), comme dans la version HTML."""
    active = active or {}
    diving = getattr(S, "wall_theme", "pierre") == "eau"
    s = CELL / 30.0
    swing = math.sin(walk_phase) * 5 * s
    alpha = 150 if ghost else 255
    size = int(CELL * 2.6)
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    cx, cy = size / 2, size / 2

    # aura de pouvoir dessinee EN PREMIER (donc derriere le corps qui sera
    # dessine par-dessus juste apres) : elle ne peut ainsi jamais recouvrir
    # ni cacher le personnage, quelle que soit sa position dans l'ellipse.
    if active.get("dimension"):
        _draw_dimension_aura(surf, (cx, cy - 1 * s), s, t)
    elif active.get("vampirisme"):
        _draw_vampire_vapor(surf, (cx, cy - 1 * s), s, t)
    elif has_power:
        _draw_power_smoke_aura(surf, (cx, cy - 1 * s), s, t)

    # --- Trainee de vitesse : stries lumineuses derriere le sens de marche ---
    if active.get("vitesse"):
        bdx = 1 if facing == "left" else (-1 if facing == "right" else 0)
        bdy = 1 if facing == "up" else (-1 if facing == "down" else 0)
        for i in range(1, 4):
            a = max(0, int(255 * 0.55 / i))
            col = (255, 235, 120, a)
            x1 = cx + bdx * 6 * s * i
            y1 = cy + 1 * s + bdy * 6 * s * i
            x2 = cx + bdx * (6 * i + 4) * s
            y2 = cy + 1 * s + bdy * (6 * i + 4) * s
            pygame.draw.line(surf, col, (x1, y1), (x2, y2), max(1, int(1.6 * s)))

    off_x, off_y = 0.0, 0.0
    if facing == "left":
        off_x = -1.5 * s
    elif facing == "right":
        off_x = 1.5 * s
    elif facing == "up":
        off_y = -1.5 * s
    elif facing == "down":
        off_y = 1.5 * s

    col_shadow = (0, 0, 0, min(alpha, 70))
    if diving:
        col_legs = (25, 40, 58, alpha)           # combinaison de plongee
        col_belt = (255, 140, 40, alpha)         # ceinture de lestage orange vif
        col_body = (30, 48, 68, alpha)           # combinaison neoprene sombre
        col_body_shade = (20, 130, 150, alpha)   # liseres cyan de la combinaison
    else:
        col_legs = (43, 43, 64, alpha)
        col_belt = (70, 70, 78, alpha)
        col_body = (222, 220, 216, alpha)        # veste blanche legerement assombrie
        col_body_shade = (172, 170, 166, alpha)  # pans/couture de la veste, plus sombres

    # ombre (douce, degradee)
    _draw_soft_ellipse_shadow(surf, (cx, cy + 10 * s), 9 * s, 3 * s, max_alpha=80)

    # jambes : vraie foulee alternee (une jambe en avant, l'autre en arriere,
    # jamais du meme cote -> les pieds ne se croisent plus), avec un genou qui
    # se plie et un pied qui decolle legerement du sol au milieu du mouvement,
    # puis se repose aux deux extremes de la foulee - comme une marche reelle.
    leg_w = max(2, int(3.2 * s))
    stride = 2.2 * s
    lift = 2.0 * s
    hip_y = cy + 4 * s
    foot_y = cy + 10 * s
    for hip_x, phase_off in ((cx - 3 * s, 0.0), (cx + 3 * s, math.pi)):
        ph = walk_phase + phase_off
        raise_amt = max(0.0, math.cos(ph))
        fx = hip_x + math.sin(ph) * stride
        fy = foot_y - raise_amt * lift
        knee_x = (hip_x + fx) / 2
        knee_y = (hip_y + fy) / 2 - raise_amt * lift * 0.4
        pygame.draw.line(surf, col_legs, (hip_x, hip_y), (knee_x, knee_y), leg_w)
        pygame.draw.line(surf, col_legs, (knee_x, knee_y), (fx, fy), leg_w)
        if diving:
            fdx, fdy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.get(facing, (0, 1))
            tip_x, tip_y = fx + fdx * 3.4 * s, fy + fdy * 3.4 * s
            side_x, side_y = -fdy, fdx
            fin = [(fx - side_x * 1.6 * s, fy - side_y * 1.6 * s),
                   (fx + side_x * 1.6 * s, fy + side_y * 1.6 * s), (tip_x, tip_y)]
            pygame.draw.polygon(surf, (245, 140, 20, alpha), fin)
        else:
            pygame.draw.circle(surf, col_legs, (int(fx), int(fy)), leg_w // 2)

    # bras : Super Force = bras qui grossissent avec des biceps visibles
    superforce = active.get("superforce")
    arm_w = max(2, int((5.4 if superforce else 2.6) * s))
    col_skin = (219, 160, 110, alpha) if superforce else (201, 138, 94, alpha)
    pygame.draw.line(surf, col_skin, (cx - 5 * s, cy - 2 * s), (cx - 5 * s - swing, cy + 5 * s), arm_w)
    pygame.draw.line(surf, col_skin, (cx + 5 * s, cy - 2 * s), (cx + 5 * s + swing, cy + 5 * s), arm_w)
    if superforce:
        pygame.draw.circle(surf, col_skin, (int(cx - 5.3 * s), int(cy + 0.3 * s)), int(2.5 * s))
        pygame.draw.circle(surf, col_skin, (int(cx + 5.3 * s), int(cy + 0.3 * s)), int(2.5 * s))

    # lampe torche tenue dans la main droite, pointee dans la direction
    # regardee : visible des qu'un halo de lampe torche eclaire la scene
    # (stade sombre ou autre dimension), pour bien montrer que c'est elle
    # qui eclaire, et non le corps du joueur.
    if torch:
        hand_x, hand_y = cx + 5 * s + swing, cy + 5 * s
        tdx, tdy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[facing]
        tip_x, tip_y = hand_x + tdx * 6 * s, hand_y + tdy * 6 * s
        pygame.draw.line(surf, (58, 58, 64, alpha), (hand_x, hand_y), (tip_x, tip_y), max(2, int(2.3 * s)))
        tip = (int(tip_x), int(tip_y))
        _radial_glow(surf, tip, 7 * s, (255, 236, 170), 175, steps=5)
        pygame.draw.circle(surf, (255, 248, 214, alpha), tip, max(2, int(1.6 * s)))

    # torse (trapeze, plus large en Super Force) : veste blanche legerement
    # sombre, avec un col ouvert en V et une couture centrale plus foncee
    # pour bien lire "veste" plutot qu'un simple bloc de couleur uni.
    body_top = 6.6 * s if superforce else 5.5 * s
    body_bot = 5.2 * s if superforce else 4.5 * s
    torso = [(cx - body_top, cy - 3 * s), (cx + body_top, cy - 3 * s),
             (cx + body_bot, cy + 6 * s), (cx - body_bot, cy + 6 * s)]
    pygame.draw.polygon(surf, col_body, torso)
    pygame.draw.polygon(surf, (0, 0, 0, min(alpha, 60)), torso, width=1)
    pygame.draw.line(surf, col_body_shade, (cx - body_top * 0.6, cy - 3 * s), (cx, cy + 2 * s), max(1, int(1.4 * s)))
    pygame.draw.line(surf, col_body_shade, (cx + body_top * 0.6, cy - 3 * s), (cx, cy + 2 * s), max(1, int(1.4 * s)))
    pygame.draw.line(surf, col_body_shade, (cx, cy + 2 * s), (cx, cy + 5.5 * s), max(1, int(1.1 * s)))

    # ceinture
    pygame.draw.rect(surf, col_belt, (cx - 4.5 * s, cy + 3.2 * s, 9 * s, 1.6 * s))

    # tete : sphere-univers (galaxie animee) plutot qu'un visage classique -
    # concept original de tete-galaxie, avec une tenue qui nous est propre.
    head_cx, head_cy = cx + off_x, cy + off_y - 6 * s
    _draw_realistic_head(surf, (head_cx, head_cy), 4.6 * s, t, facing)
    if active.get("vampirisme"):
        _draw_vampire_hood(surf, (head_cx, head_cy), 4.6 * s, alpha)

    if diving:
        # masque de plongee (verre cyan translucide) + tuba recourbe sur le cote
        mask_r = 4.0 * s
        mask_rect = (head_cx - mask_r, head_cy - mask_r * 0.7, mask_r * 2, mask_r * 1.5)
        pygame.draw.ellipse(surf, (30, 30, 34, alpha), mask_rect, width=max(1, int(0.9 * s)))
        pygame.draw.ellipse(surf, (150, 230, 255, min(alpha, 150)), mask_rect)
        snork_x = head_cx + 4.6 * s
        pygame.draw.line(surf, (255, 140, 40, alpha), (snork_x, head_cy - 1 * s),
                          (snork_x, head_cy - 8 * s), max(2, int(1.2 * s)))
        pygame.draw.line(surf, (255, 140, 40, alpha), (snork_x, head_cy - 8 * s),
                          (snork_x - 2 * s, head_cy - 9.5 * s), max(2, int(1.2 * s)))

    # --- Auras qui enveloppent tout le personnage, centrees sur le corps ---
    body_c = (int(cx), int(cy - 1 * s))

    if active.get("invincible"):
        n = 5
        rot = (t or 0.0) * 3.8
        for i in range(n):
            a = rot + (i / n) * 2 * math.pi
            x1 = body_c[0] + math.cos(a) * 8 * s
            y1 = body_c[1] + math.sin(a) * 8 * s
            x2 = body_c[0] + math.cos(a) * 10.5 * s
            y2 = body_c[1] + math.sin(a) * 10.5 * s
            pygame.draw.line(surf, (255, 215, 64, 220), (x1, y1), (x2, y2), max(1, int(1.2 * s)))

    if active.get("phase"):
        dash_surf_r = 9.5 * s
        n_dash = 10
        for i in range(n_dash):
            if i % 2 == 0:
                a0 = (i / n_dash) * 2 * math.pi
                a1 = ((i + 1) / n_dash) * 2 * math.pi
                rect = (body_c[0] - dash_surf_r, body_c[1] - dash_surf_r, dash_surf_r * 2, dash_surf_r * 2)
                pygame.draw.arc(surf, (200, 180, 255, 180), rect, a0, a1, max(1, int(1.3 * s)))

    # Bouclier : une bulle transparente et brillante qui enveloppe tout le corps.
    if active.get("shield"):
        pulse = 1 + math.sin((t or 0.0) * 3.3) * 0.05
        r = 10.5 * s * pulse
        _radial_glow(surf, body_c, r, (143, 211, 255), 90, steps=6)
        pygame.draw.circle(surf, (210, 242, 255, 220), body_c, int(r), max(1, int(1.3 * s)))

    screen.blit(surf, (sx - cx, sy - cy))


def _get_vignette(w, h):
    """Vignette (bords assombris) mise en cache par taille d'ecran : reutilise
    la technique du 'trou' de _get_glow_hole_mask pour degrader doucement."""
    surf = _VIGNETTE_CACHE.get((w, h))
    if surf is not None:
        return surf
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    surf.fill((8, 6, 14, 150))
    r = max(w, h) * 0.68
    mask = _get_glow_hole_mask(r)
    rect = mask.get_rect(center=(w // 2, h // 2))
    surf.blit(mask, rect.topleft, special_flags=pygame.BLEND_RGBA_SUB)
    _VIGNETTE_CACHE[(w, h)] = surf
    return surf


_VIGNETTE_CACHE = {}
_shake_until = 0.0
_shake_mag = 0.0
_level_transition_start = -10.0
_level_transition_until = -10.0
LEVEL_TRANSITION_DURATION = 0.7


def trigger_shake(magnitude, duration):
    """Declenche un tremblement d'ecran (choc violent : coup de Force,
    explosion, mur qui casse...)."""
    global _shake_until, _shake_mag
    _shake_until = now() + duration
    _shake_mag = magnitude


def start_level_transition(t):
    """Petit fondu au noir puis retour, joue au changement automatique de
    niveau au lieu d'un cut brutal."""
    global _level_transition_start, _level_transition_until
    _level_transition_start = t
    _level_transition_until = t + LEVEL_TRANSITION_DURATION


def draw_level_transition(t):
    if t >= _level_transition_until:
        return
    prog = (t - _level_transition_start) / LEVEL_TRANSITION_DURATION
    a = int(max(0, min(255, 255 * (1 - abs(prog * 2 - 1)))))
    if a > 0:
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, a))
        screen.blit(overlay, (0, 0))


def draw_reward_popup(t):
    """Petite animation qui presente, juste apres le changement de niveau,
    la recompense gagnee (un pouvoir utile pour la suite) ainsi que le
    detail des points marques au niveau precedent."""
    reward = S.reward_popup
    if not reward or t >= S.reward_popup_until:
        return
    remain = S.reward_popup_until - t
    age = REWARD_POPUP_DURATION - remain
    prog_in = min(1.0, age / 0.3)
    prog_out = min(1.0, remain / 0.5)
    alpha = int(255 * min(prog_in, prog_out))
    if alpha <= 0:
        return
    scale = 0.82 + 0.18 * prog_in

    card_w, card_h = 360, 168
    cx, cy = WIDTH / 2, HEIGHT / 2 - 30

    card = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
    pygame.draw.rect(card, (20, 18, 30, min(235, alpha)), (0, 0, card_w, card_h), border_radius=16)
    pygame.draw.rect(card, (255, 215, 0, alpha), (0, 0, card_w, card_h), width=2, border_radius=16)
    scaled = pygame.transform.smoothscale(card, (max(1, int(card_w * scale)), max(1, int(card_h * scale))))
    screen.blit(scaled, (cx - scaled.get_width() / 2, cy - scaled.get_height() / 2))

    d = reward["power"]
    icon_cy = cy - card_h / 2 + 42
    pygame.draw.circle(screen, d["color"], (int(cx), int(icon_cy)), 26)
    pygame.draw.circle(screen, (255, 255, 255), (int(cx), int(icon_cy)), 26, width=2)
    draw_power_icon(screen, cx, icon_cy, 26, d["id"])

    draw_text(screen, "Recompense obtenue : %s !" % d["name"], FONT_MED, COL_TEXT,
              cx, cy - card_h / 2 + 82, center=True)
    draw_text(screen, "+%d points au niveau precedent" % reward["points"], FONT_SMALL, COL_DOOR_OUT,
              cx, cy - card_h / 2 + 108, center=True)
    draw_text(screen, "Elle t'attend dans l'inventaire pour ce niveau-ci.", FONT_SMALL, COL_DIM,
              cx, cy - card_h / 2 + 130, center=True)


_title_particles = []


def draw_title_screen(t):
    if not _title_particles:
        for _ in range(40):
            _title_particles.append({
                "x": random.uniform(0, WIDTH), "y": random.uniform(0, HEIGHT),
                "r": random.uniform(1.5, 4.0), "speed": random.uniform(8, 24),
                "phase": random.uniform(0, math.tau),
            })
    draw_vertical_gradient(screen, COL_BG_TOP, COL_BG_BOTTOM)
    for p in _title_particles:
        p["y"] -= p["speed"] / 60.0
        if p["y"] < -10:
            p["y"] = HEIGHT + 10
            p["x"] = random.uniform(0, WIDTH)
        sway = math.sin(t * 0.6 + p["phase"]) * 12
        glow = 0.6 + 0.4 * math.sin(t * 2.2 + p["phase"])
        col = (int(160 + 60 * glow), int(140 + 60 * glow), 255)
        pygame.draw.circle(screen, col, (int(p["x"] + sway), int(p["y"])), int(p["r"]))
    draw_text(screen, "LE LABYRINTHE", FONT_TITLE, COL_TEXT, WIDTH / 2, HEIGHT / 2 - 40, center=True)
    if int(t * 1.6) % 2 == 0:
        draw_text(screen, "Appuie sur ENTREE pour commencer", FONT_MED, COL_DIM,
                  WIDTH / 2, HEIGHT / 2 + 20, center=True)
    draw_text(screen, "Cree par LONTIO KESSEL", FONT_SMALL, COL_DIM, WIDTH / 2, HEIGHT - 64, center=True)
    draw_text(screen, "lontiokessel@gmail.com   |   WhatsApp : +237 650196251", FONT_SMALL, COL_DIM,
              WIDTH / 2, HEIGHT - 46, center=True)
    draw_text(screen, "github.com/LONTIo-RICHY", FONT_SMALL, COL_DIM, WIDTH / 2, HEIGHT - 28, center=True)
    draw_text(screen, "F4 : quitter definitivement le jeu", FONT_TINY, COL_DIM, WIDTH / 2, HEIGHT - 10, center=True)


def _apply_wave_distortion(surf, t, amplitude=3.0, wavelength=26.0, speed=2.2, step=4):
    """Distorsion en bandes horizontales decalees par une onde sinusoidale :
    effet de mirage/onde qui rend la scene irreelle. La base (copie non
    distordue) est gardee sous les bandes pour qu'aucun bord ne laisse de
    trou transparent quand le decalage revele le bord de l'image."""
    w, h = surf.get_size()
    out = surf.copy()
    for y in range(0, h, step):
        offset = int(math.sin((y / wavelength) + t * speed) * amplitude)
        if offset == 0:
            continue
        band_h = min(step, h - y)
        band = surf.subsurface((0, y, w, band_h)).copy()
        out.blit(band, (offset, y))
    return out


def draw_radar(cam_x, cam_y):
    dx = S.exit["x"] - S.anim["px"]
    dy = S.exit["y"] - S.anim["py"]
    if abs(dx) < 0.001 and abs(dy) < 0.001:
        return
    ang = math.atan2(dy, dx)
    cx, cy = GAME_X + GAME_W / 2, GAME_Y + 20
    p1 = (cx + math.cos(ang) * 12, cy + math.sin(ang) * 12)
    p2 = (cx + math.cos(ang + 2.5) * 8, cy + math.sin(ang + 2.5) * 8)
    p3 = (cx + math.cos(ang - 2.5) * 8, cy + math.sin(ang - 2.5) * 8)
    pygame.draw.polygon(screen, COL_DOOR_OUT, [p1, p2, p3])


def draw_minimap(cam_x, cam_y, show_monsters=False):
    box = 90
    bx, by = GAME_X + GAME_W - box - 8, GAME_Y + 8
    surf = pygame.Surface((box, box), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 140))
    pygame.draw.rect(surf, (255, 255, 255, 100), surf.get_rect(), width=1)
    sxr, syr = box / S.cols, box / S.rows
    pygame.draw.circle(surf, COL_DOOR_IN, (0, 0), 3)
    pygame.draw.circle(surf, COL_DOOR_OUT, (int(S.exit["x"] * sxr), int(S.exit["y"] * syr)), 3)
    pygame.draw.circle(surf, COL_PLAYER, (int(S.anim["px"] * sxr), int(S.anim["py"] * syr)), 3)
    if show_monsters:
        for mo in S.monsters:
            pygame.draw.circle(surf, (150, 90, 200),
                                (int(mo["anim"]["px"] * sxr), int(mo["anim"]["py"] * syr)), 3)
    screen.blit(surf, (bx, by))


# ----------------------------------------------------------------------
# HUD (haut / bas de l'ecran)
# ----------------------------------------------------------------------
def format_hearts():
    return "coeur x " + str(max(0, S.lives))


def draw_help_button():
    """Petit bouton "?" toujours visible (coin haut-droit) : clique ou touche
    H pour ouvrir/fermer le panneau qui explique chaque pouvoir."""
    global HELP_BTN_RECT
    r = 15
    cx, cy = WIDTH - 24, 24
    HELP_BTN_RECT = pygame.Rect(cx - r, cy - r, r * 2, r * 2)
    pygame.draw.circle(screen, (42, 40, 60), (cx, cy), r)
    pygame.draw.circle(screen, COL_DOOR_OUT if S.show_help else COL_TEXT, (cx, cy), r, width=2)
    draw_text(screen, "?", FONT_MED, COL_TEXT, cx, cy, center=True, shadow=False)


def wrap_text(text, font, max_width):
    words = text.split(" ")
    lines = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if cur == "" or font.size(trial)[0] <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_help_overlay():
    """Panneau semi-transparent expliquant chaque pouvoir (nom + pictogramme
    + une phrase), ouvert via le bouton "?" ou la touche H."""
    veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    veil.fill((10, 10, 20, 175))
    screen.blit(veil, (0, 0))

    margin = max(16, int(min(WIDTH, HEIGHT) * 0.04))
    panel = pygame.Rect(margin, margin, WIDTH - margin * 2, HEIGHT - margin * 2)
    panel_surf = pygame.Surface((panel.width, panel.height), pygame.SRCALPHA)
    panel_surf.fill((28, 26, 40, 235))
    pygame.draw.rect(panel_surf, (255, 255, 255, 60), panel_surf.get_rect(), width=2, border_radius=14)
    screen.blit(panel_surf, (panel.x, panel.y))

    draw_text(screen, "Les pouvoirs", FONT_TITLE, COL_TEXT, panel.centerx, panel.y + 24, center=True)
    draw_text(screen, "Clique sur (?) ou appuie sur H pour fermer", FONT_SMALL, COL_DIM,
              panel.centerx, panel.y + 48, center=True)

    items = POWER_TYPES
    cols = 2
    rows = math.ceil(len(items) / cols)
    top = panel.y + 68
    avail_h = max(rows * 30, panel.height - 84)
    row_h = avail_h / rows
    col_w = panel.width / cols
    icon_r = min(13, row_h / 3.2)

    for i, d in enumerate(items):
        col = i // rows
        row = i % rows
        x = panel.x + 16 + col * col_w
        y = top + row * row_h
        icon_cx, icon_cy = x + icon_r, y + icon_r
        pygame.draw.circle(screen, d["color"], (int(icon_cx), int(icon_cy)), int(icon_r))
        pygame.draw.circle(screen, (255, 255, 255), (int(icon_cx), int(icon_cy)), int(icon_r), width=1)
        draw_power_icon(screen, icon_cx, icon_cy, icon_r, d["id"])
        name_x = x + icon_r * 2 + 10
        draw_text(screen, d["name"], FONT_SMALL, COL_TEXT, name_x, y + 1, shadow=False)
        desc = POWER_DESCRIPTIONS.get(d["id"], "")
        max_w = col_w - (icon_r * 2 + 26)
        lines = wrap_text(desc, FONT_TINY, max_w)
        max_lines = max(1, int((row_h - 18) / 13))
        for j, line in enumerate(lines[:max_lines]):
            draw_text(screen, line, FONT_TINY, COL_DIM, name_x, y + 17 + j * 13, shadow=False)


def draw_hud_top():
    draw_text(screen, "LE LABYRINTHE", FONT_TITLE, COL_TEXT, WIDTH / 2, 26, center=True)

    level_label = "Niveau %d (BOSS)" % S.level if S.is_boss_level else "Niveau %d" % S.level
    info = "%s    Coups %d    Vies %s    Points %d" % (level_label, S.moves, format_hearts(), S.score)
    draw_text(screen, info, FONT_MED, COL_TEXT, WIDTH / 2, 58, center=True)

    if not S.monsters:
        if S.level < MONSTER_START_LEVEL:
            mtext = "Aucun monstre pour l'instant... il rodera a partir du niveau %d." % MONSTER_START_LEVEL
        else:
            mtext = "Aucun monstre ce niveau."
    elif len(S.monsters) == 1:
        mtext = "Un monstre rode - menace %d/5" % (S.monsters[0]["tier"] + 1)
    else:
        mtext = "%d monstres rodent (dedoubles !) - menace %d/5" % (
            len(S.monsters), S.monsters[0]["tier"] + 1)
    draw_text(screen, mtext, FONT_SMALL, COL_DIM, WIDTH / 2, 84, center=True)

    t = now()

    # Defi du niveau et bonus de rapidite discret : un simple compte a
    # rebours dans le HUD (pas d'urgence visuelle intrusive), plus l'etat
    # (en cours / rate) du defi annonce en debut de niveau.
    status_bits = []
    if S.challenge:
        ok = challenge_still_valid()
        status_bits.append("Defi : %s [%s]" % (S.challenge["desc"], "en cours" if ok else "rate"))
    remaining_speed = SPEED_BONUS_SECONDS - (t - S.level_start_time)
    if remaining_speed > 0:
        status_bits.append("Bonus rapidite encore %ds" % int(math.ceil(remaining_speed)))
    if status_bits and not S.won and not S.game_over:
        draw_text(screen, "   |   ".join(status_bits), FONT_SMALL, COL_DOOR_OUT, WIDTH / 2, 100, center=True)
    parts = []
    if S.cheat_active:
        parts.append("TRICHE : pouvoirs illimites (ce niveau)")
    else:
        checks = [
            ("superforce", "Super Force"), ("invisible", "Invisibilite"), ("vitesse", "Vitesse"),
            ("vision", "Vision totale"), ("radar", "Radar de sortie"), ("dimension", "Autre Dimension"),
            ("doublepas", "Double Pas"), ("aimant", "Aimant Sortie"), ("invincible", "Invincibilite"),
            ("gel", "Gel du monstre"),
        ]
        for key, label in checks:
            end = S.effects.get(key, 0)
            if end and t < end:
                parts.append("%s (%ds)" % (label, int(math.ceil(end - t))))
        # Vampirisme : tant qu'aucun monstre n'a ete mordu, le pouvoir n'a pas
        # de compte a rebours (recherche illimitee) ; le compte a rebours
        # (08s) n'apparait qu'une fois la morsure faite.
        if S.vampire_bat:
            if S.vampire_bat.get("state") == "latched":
                end = S.effects.get("vampirisme", 0)
                if end and t < end:
                    parts.append("Vampirisme (%ds)" % int(math.ceil(end - t)))
            else:
                parts.append("Vampirisme (en approche)")
        if S.effects.get("shield_charges", 0) > 0:
            parts.append("Bouclier pret x%d" % S.effects["shield_charges"])
        if S.effects.get("phase_charges", 0) > 0:
            parts.append("Phasage pret x%d" % S.effects["phase_charges"])
    badge = "  |  ".join(parts) if parts else "Aucun pouvoir actif"
    color = COL_CHEAT if S.cheat_active else COL_TEXT
    draw_text(screen, badge, FONT_SMALL, color, WIDTH / 2, 128, center=True)

    # inventaire : chaque pouvoir est represente par un petit dessin (pictogramme)
    # qui evoque son effet, en plus de son nom et de son compteur.
    items = inventory_list()
    if not items:
        draw_text(screen, "Inventaire : (vide)", FONT_SMALL, COL_TEXT, WIDTH / 2, 152, center=True)
    else:
        draw_text(screen, "Inventaire (TAB = choisir, ENTREE = utiliser)", FONT_SMALL, COL_DIM,
                  WIDTH / 2, 152, center=True)
        sel = min(S.selected_index, len(items) - 1)
        icon_d = 30
        text_gap = 8
        slot_gap = 24
        y_row = 180

        slots = []
        for i, d in enumerate(items):
            n = S.inventory_counts[d["id"]]
            txt_surf = FONT_SMALL.render("%s x%d" % (d["name"], n), True, COL_TEXT)
            width = icon_d + text_gap + txt_surf.get_width()
            slots.append((d, txt_surf, width, i == sel))

        total_w = sum(sl[2] for sl in slots) + slot_gap * (len(slots) - 1)
        x = WIDTH / 2 - total_w / 2
        for d, txt_surf, width, is_sel in slots:
            icon_cx = x + icon_d / 2
            icon_cy = y_row
            if is_sel:
                pygame.draw.circle(screen, COL_DOOR_OUT, (int(icon_cx), int(icon_cy)),
                                    int(icon_d / 2) + 4, width=2)
            pygame.draw.circle(screen, d["color"], (int(icon_cx), int(icon_cy)), int(icon_d / 2))
            pygame.draw.circle(screen, (255, 255, 255), (int(icon_cx), int(icon_cy)), int(icon_d / 2), width=1)
            draw_power_icon(screen, icon_cx, icon_cy, icon_d / 2, d["id"])
            screen.blit(txt_surf, (x + icon_d + text_gap, y_row - txt_surf.get_height() / 2))
            x += width + slot_gap

    if S.toast_text and now() < S.toast_until:
        draw_text(screen, S.toast_text, FONT_MED, COL_DOOR_OUT, WIDTH / 2, 214, center=True)
    elif S.msg:
        draw_text(screen, S.msg, FONT_MED, COL_DOOR_OUT, WIDTH / 2, 214, center=True)

    draw_help_button()


def draw_hud_bottom():
    y = GAME_Y + GAME_H + 20
    lines = [
        "Fleches / Z Q S D : se deplacer      TAB : changer de pouvoir      ENTREE : utiliser",
        "R : recommencer      M : son      P : pause      F11 / ALT+ENTREE : plein ecran      "
        "Echap : quitter      F4 : quitter definitivement",
        "Entree = vert   Sortie = jaune   Toi = rouge   Monstre = evolue chaque niveau",
    ]
    for i, line in enumerate(lines):
        draw_text(screen, line, FONT_SMALL, COL_DIM, WIDTH / 2, y + i * 22, center=True)


def draw_game_over_overlay():
    """Ecran de defaite : assombrit tout l'ecran par-dessus le camp (qui
    restait visible, fige, juste derriere) pour bien mettre en avant, au
    premier plan et non plus discretement en arriere-plan, le choix propose
    au joueur (recommencer au niveau 1, ou rejouer ce niveau)."""
    veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    veil.fill((20, 4, 8, 210))
    screen.blit(veil, (0, 0))
    draw_text(screen, "NIVEAU PERDU", FONT_TITLE, COL_TEXT, WIDTH / 2, HEIGHT / 2 - 46, center=True)
    draw_text(screen, "Tu as perdu toutes tes vies sur ce niveau.", FONT_MED, COL_DIM,
              WIDTH / 2, HEIGHT / 2 - 12, center=True)
    draw_text(screen, "R : recommencer depuis le niveau 1", FONT_MED, COL_TEXT,
              WIDTH / 2, HEIGHT / 2 + 20, center=True)
    draw_text(screen, "ENTREE ou ESPACE : rejouer ce niveau", FONT_MED, COL_TEXT,
              WIDTH / 2, HEIGHT / 2 + 46, center=True)


def draw_pause_overlay():
    """Assombrit tout l'ecran et affiche 'PAUSE' par-dessus, sans toucher a l'etat
    du jeu en dessous (qui reste fige tant que la pause est active)."""
    veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    veil.fill((10, 10, 16, 190))
    screen.blit(veil, (0, 0))
    draw_text(screen, "PAUSE", FONT_TITLE, COL_TEXT, WIDTH / 2, HEIGHT / 2 - 24, center=True)
    draw_text(screen, "Le jeu est en pause - P pour reprendre", FONT_MED, COL_DIM,
              WIDTH / 2, HEIGHT / 2 + 14, center=True)
    draw_text(screen, "(R pour recommencer, Echap pour quitter)", FONT_SMALL, COL_DIM,
              WIDTH / 2, HEIGHT / 2 + 42, center=True)


# ----------------------------------------------------------------------
# Boucle principale
# ----------------------------------------------------------------------
def main():
    global _muted, window, _windowed_size, _in_title
    new_game()
    setup_level()
    _in_title = True

    key_dir_map = {
        pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left", pygame.K_RIGHT: "right",
        pygame.K_z: "up", pygame.K_s: "down", pygame.K_q: "left", pygame.K_d: "right", pygame.K_w: "up",
    }

    running = True
    while running:
        t = now()

        if _in_title:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE:
                    if not _is_fullscreen:
                        _windowed_size = (max(320, event.w), max(240, event.h))
                        window = pygame.display.set_mode(_windowed_size, pygame.RESIZABLE)
                        recompute_layout(*window.get_size())
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_F4:
                        running = False  # sortie definitive du jeu, demandee explicitement
                    elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                        _in_title = False
                        # Le joueur vient seulement de commencer a jouer : on
                        # relance les decomptes d'inactivite/instabilite ici,
                        # sinon le temps passe sur l'ecran-titre comptait deja
                        # comme du temps "sans bouger" et pouvait declencher
                        # un remaniement des murs des la premiere frame de jeu.
                        S.last_move_time = t
                        S.last_unstable_reshuffle_at = t
            draw_title_screen(t)
            _present()
            clock.tick(60)
            continue

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                if not _is_fullscreen:
                    _windowed_size = (max(320, event.w), max(240, event.h))
                    window = pygame.display.set_mode(_windowed_size, pygame.RESIZABLE)
                    recompute_layout(*window.get_size())
            elif event.type == pygame.KEYUP:
                if event.key in key_dir_map:
                    d = key_dir_map[event.key]
                    if d in S.held_dirs:
                        S.held_dirs.remove(d)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if HELP_BTN_RECT and HELP_BTN_RECT.collidepoint(event.pos):
                    toggle_help()
                elif S.show_help:
                    close_help()  # un clic en dehors du bouton referme aussi le panneau (et la pause douce)
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if S.show_help:
                        close_help()
                    elif _is_fullscreen:
                        toggle_fullscreen()
                    else:
                        running = False
                elif event.key == pygame.K_F4:
                    running = False  # sortie definitive du jeu, demandee explicitement, quel que soit l'etat
                elif event.key in (pygame.K_F11, pygame.K_RETURN) and (
                        event.key == pygame.K_F11 or (pygame.key.get_mods() & pygame.KMOD_ALT)):
                    toggle_fullscreen()
                elif event.key == pygame.K_p:
                    toggle_pause()
                elif event.key == pygame.K_r:
                    restart_game()
                elif S.game_over and event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                    retry_level()
                elif event.key == pygame.K_m:
                    _muted = not _muted
                    if _MIXER_OK:
                        pygame.mixer.music.set_volume(0.0 if _muted else 0.35)
                elif event.key == pygame.K_h:
                    toggle_help()
                elif S.show_help:
                    pass  # panneau d'aide ouvert : on ignore deplacement / TAB / pouvoirs
                elif is_paused():
                    pass  # jeu en pause : on ignore deplacement / TAB / pouvoirs
                elif event.key == pygame.K_TAB:
                    cycle_selection()
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
                    activate_selected_power()
                elif event.key in key_dir_map:
                    d = key_dir_map[event.key]
                    move(d)  # nouvel appui : les pouvoirs de traversee/casse de mur peuvent se declencher
                    if d in S.held_dirs:
                        S.held_dirs.remove(d)
                    S.held_dirs.append(d)  # la direction la plus recemment enfoncee est suivie en priorite

                # detection du code de triche (clavier physique, lettres tapees) - pas pendant
                # la pause ni quand le panneau d'aide est ouvert
                if not is_paused() and not S.show_help and event.unicode and event.unicode.isalpha():
                    handle_cheat_key(event.unicode)

        # passage automatique au niveau suivant apres la victoire (fige pendant la pause)
        if S.won and S.win_at is not None and t >= S.win_at:
            reward = S.pending_reward
            S.level += 1
            S.lives = 3
            setup_level()
            if reward:
                # la recompense du niveau precedent est donnee maintenant,
                # une fois l'inventaire du nouveau niveau deja en place,
                # pour vraiment aider a affronter la suite.
                power = reward["power"]
                S.inventory_counts[power["id"]] = S.inventory_counts.get(power["id"], 0) + 1
                S.reward_popup = reward
                S.reward_popup_until = t + REWARD_POPUP_DURATION
            S.pending_reward = None
            start_level_transition(t)

        # Maintien de touche : tant qu'une direction reste enfoncee, on
        # enchaine les pas automatiquement (des que le pas precedent est
        # termine) au lieu d'exiger un appui par case. Les pouvoirs de
        # traversee/casse de mur restent reserves au tout premier appui
        # (voir allow_wall_powers=False ci-dessous).
        if not is_paused() and not S.show_help and not S.game_over and not S.won and S.held_dirs:
            move(S.held_dirs[-1], allow_wall_powers=False)

        if not is_paused():
            update_player_anim(t)
            update_monsters(t)
            update_camp_reshuffle(t)
            check_idle_reshuffle(t)
            check_unstable_reshuffle(t)
            update_mirror(t)
            update_vampire_bat(t)
            update_temp_walls(t)
            update_particles()

        draw_vertical_gradient(screen, COL_BG_TOP, COL_BG_BOTTOM)
        draw_hud_top()
        draw_game_area(t)
        draw_hud_bottom()
        if is_paused() and not S.show_help:
            draw_pause_overlay()
        if S.show_help:
            draw_help_overlay()
        if S.game_over:
            draw_game_over_overlay()
        draw_level_transition(t)
        draw_reward_popup(t)

        _present()
        clock.tick(60)

    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
