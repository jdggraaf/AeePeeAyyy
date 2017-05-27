# Common Pokemon - seen by every account
COMMON_POKEMON = [
    16,     # Pidgey
    19,     # Rattata
    23,     # Ekans
    27,     # Sandshrew
    29,     # Nidoran F
    32,     # Nidoran M
    41,     # Zubat
    43,     # Oddish
    46,     # Paras
    52,     # Meowth
    54,     # Psyduck
    60,     # Poliwag
    69,     # Bellsprout
    72,     # Tentacool
    74,     # Geodude
    81,     # Magnemite
    98,     # Krabby
    118,    # Goldeen
    120,    # Staryu
    129,    # Magikarp
    161,    # Sentret
    165,    # Ledyba
    167,    # Spinarak
    177,    # Natu
    183,    # Marill
    187,    # Hoppip
    191,    # Sunkern
    194,    # Wooper
    198,    # Murkrow
    209,    # Snubbull
    218     # Slugma
]

def sees_shadowed_pokemon(api_response):
    cells = api_response.get('responses', {}).get('GET_MAP_OBJECTS', {}).get(
        'map_cells', [])
    for cell in cells:
        for p in cell.get('wild_pokemons', []):
            pid = p['pokemon_data']['pokemon_id']
            if pid not in COMMON_POKEMON:
                return True
        for p in cell.get('nearby_pokemons', []):
            pid = p['pokemon_id']
            if pid not in COMMON_POKEMON:
                return True
    return False
