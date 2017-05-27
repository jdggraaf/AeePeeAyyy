#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
import time
import random
from threading import Lock
from timeit import default_timer

from pgoapi import PGoApi
from pgoapi.exceptions import AuthException
from pgoapi.protos.pogoprotos.inventory.item.item_id_pb2 import *

from pogom.shadow import sees_shadowed_pokemon
from .fakePogoApi import FakePogoApi
from .utils import (in_radius, generate_device_info, equi_rect_distance,
                    get_new_api_timestamp)
from .proxy import get_new_proxy

log = logging.getLogger(__name__)


class TooManyLoginAttempts(Exception):
    pass


# Create the API object that'll be used to scan.
def setup_api(args, status):
    # Create the API instance this will use.
    if args.mock != '':
        api = FakePogoApi(args.mock)
    else:
        device_info = generate_device_info()
        api = PGoApi(device_info=device_info)

    # New account - new proxy.
    if args.proxy:
        # If proxy is not assigned yet or if proxy-rotation is defined
        # - query for new proxy.
        if ((not status['proxy_url']) or
                ((args.proxy_rotation is not None) and
                 (args.proxy_rotation != 'none'))):

            proxy_num, status['proxy_url'] = get_new_proxy(args)
            if args.proxy_display.upper() != 'FULL':
                status['proxy_display'] = proxy_num
            else:
                status['proxy_display'] = status['proxy_url']

    if status['proxy_url']:
        log.debug('Using proxy %s', status['proxy_url'])
        api.set_proxy({
            'http': status['proxy_url'],
            'https': status['proxy_url']})

    return api


# Use API to check the login status, and retry the login if possible.
def check_login(args, account, api, position, proxy_url):

    # Logged in? Enough time left? Cool!
    if api._auth_provider and api._auth_provider._ticket_expire:
        remaining_time = api._auth_provider._ticket_expire / 1000 - time.time()
        if remaining_time > 60:
            log.debug(
                'Credentials remain valid for another %f seconds.',
                remaining_time)
            return

    # Try to login. Repeat a few times, but don't get stuck here.
    num_tries = 0
    # One initial try + login_retries.
    while num_tries < (args.login_retries + 1):
        try:
            if proxy_url:
                api.set_authentication(
                    provider=account['auth_service'],
                    username=account['username'],
                    password=account['password'],
                    proxy_config={'http': proxy_url, 'https': proxy_url})
            else:
                api.set_authentication(
                    provider=account['auth_service'],
                    username=account['username'],
                    password=account['password'])
            break
        except AuthException:
            num_tries += 1
            log.error(
                ('Failed to login to Pokemon Go with account %s. ' +
                 'Trying again in %g seconds.'),
                account['username'], args.login_delay)
            time.sleep(args.login_delay)

    if num_tries > args.login_retries:
        log.error(
            ('Failed to login to Pokemon Go with account %s in ' +
             '%d tries. Giving up.'),
            account['username'], num_tries)
        raise TooManyLoginAttempts('Exceeded login attempts.')

    time.sleep(random.uniform(2, 4))

    try:  # 0 - empty request
        request = api.create_request()
        request.call()
        time.sleep(random.uniform(.43, .97))
    except Exception as e:
        log.debug('Login for account %s failed. Exception in call request: %s',
                  account['username'], repr(e))

    try:  # 1 - get_player
        # Get warning/banned flags and tutorial state.
        account.update(get_player_state(args, api))
        time.sleep(random.uniform(.53, 1.1))
    except Exception as e:
        log.debug('Login for account %s failed. Exception in get_player: %s',
                  account['username'], repr(e))

    # 2 - download_remote_config needed?

    try:  # 3 - get_player_profile
        request = api.create_request()
        request.get_player_profile()
        request.check_challenge()
        request.get_hatched_eggs()
        add_get_inventory_request(request, account)
        request.check_awarded_badges()
        request.download_settings()
        request.get_buddy_walked()
        response = request.call()

        update_account_from_response(account, response)
        time.sleep(random.uniform(.2, .3))
    except Exception as e:
        log.debug('Login for account %s failed. Exception in ' +
                  'get_player_profile: %s',
                  account['username'], repr(e))

    try:  # 4 - level_up_rewards
        request = api.create_request()
        request.level_up_rewards(level=account['level'])
        request.check_challenge()
        request.get_hatched_eggs()
        add_get_inventory_request(request, account)
        request.check_awarded_badges()
        request.download_settings()
        request.get_buddy_walked()
        response = request.call()

        update_account_from_response(account, response)
        time.sleep(random.uniform(.45, .7))
    except Exception as e:
        log.debug('Login for account %s failed. Exception in ' +
                  'level_up_rewards: %s',
                  account['username'], repr(e))

    try:  # 5 - register_background_device
        request = api.create_request()
        request.register_background_device(device_type='apple_watch')
        request.check_challenge()
        request.get_hatched_eggs()
        add_get_inventory_request(request, account)
        request.check_awarded_badges()
        request.get_buddy_walked()
        time.sleep(.1)
        response = request.call()

        update_account_from_response(account, response)
        time.sleep(random.uniform(.45, .7))
    except Exception as e:
        log.debug('Login for account %s failed. Exception in '
                  'register_background_device: %s', account['username'],
                  repr(e))

    log.debug('Login for account %s successful.', account['username'])
    time.sleep(random.uniform(10, 20))


# Returns warning/banned flags and tutorial state.
def get_player_state(args, api):
    request = api.create_request()
    request.get_player(
        player_locale=args.player_locale)
    response = request.call().get('responses', {})

    get_player = response.get('GET_PLAYER', {})
    return {
        'tutorial_state': get_player.get('player_data', {}).get('tutorial_state', []),
        'warn': get_player.get('warn', False),
        'banned': get_player.get('banned', False)
    }


# Complete minimal tutorial steps.
# API argument needs to be a logged in API instance.
# TODO: Check if game client bundles these requests, or does them separately.
def complete_tutorial(args, api, account, tutorial_state):
    if 0 not in tutorial_state:
        time.sleep(random.uniform(1, 5))
        request = api.create_request()
        request.mark_tutorial_complete(tutorials_completed=0)
        log.debug('Sending 0 tutorials_completed for %s.', account['username'])
        request.call()

    if 1 not in tutorial_state:
        time.sleep(random.uniform(5, 12))
        request = api.create_request()
        request.set_avatar(player_avatar={
            'hair': random.randint(1, 5),
            'shirt': random.randint(1, 3),
            'pants': random.randint(1, 2),
            'shoes': random.randint(1, 6),
            'avatar': random.randint(0, 1),
            'eyes': random.randint(1, 4),
            'backpack': random.randint(1, 5)
        })
        log.debug('Sending set random player character request for %s.',
                  account['username'])
        request.call()

        time.sleep(random.uniform(0.3, 0.5))

        request = api.create_request()
        request.mark_tutorial_complete(tutorials_completed=1)
        log.debug('Sending 1 tutorials_completed for %s.', account['username'])
        request.call()

    time.sleep(random.uniform(0.5, 0.6))
    request = api.create_request()
    request.get_player_profile()
    log.debug('Fetching player profile for %s...', account['username'])
    request.call()

    starter_id = None
    if 3 not in tutorial_state:
        time.sleep(random.uniform(1, 1.5))
        request = api.create_request()
        request.get_download_urls(asset_id=[
            '1a3c2816-65fa-4b97-90eb-0b301c064b7a/1477084786906000',
            'aa8f7687-a022-4773-b900-3a8c170e9aea/1477084794890000',
            'e89109b0-9a54-40fe-8431-12f7826c8194/1477084802881000'])
        log.debug('Grabbing some game assets.')
        request.call()

        time.sleep(random.uniform(1, 1.6))
        request = api.create_request()
        request.call()

        time.sleep(random.uniform(6, 13))
        request = api.create_request()
        starter = random.choice((1, 4, 7))
        request.encounter_tutorial_complete(pokemon_id=starter)
        log.debug('Catching the starter for %s.', account['username'])
        request.call()

        time.sleep(random.uniform(0.5, 0.6))
        request = api.create_request()
        request.get_player(
            player_locale=args.player_locale)
        responses = request.call().get('responses', {})

        inventory = responses.get('GET_INVENTORY', {}).get(
            'inventory_delta', {}).get('inventory_items', [])
        for item in inventory:
            pokemon = item.get('inventory_item_data', {}).get('pokemon_data')
            if pokemon:
                starter_id = pokemon.get('id')

    if 4 not in tutorial_state:
        time.sleep(random.uniform(5, 12))
        request = api.create_request()
        request.claim_codename(codename=account['username'])
        log.debug('Claiming codename for %s.', account['username'])
        request.call()

        time.sleep(random.uniform(1, 1.3))
        request = api.create_request()
        request.mark_tutorial_complete(tutorials_completed=4)
        log.debug('Sending 4 tutorials_completed for %s.', account['username'])
        request.call()

        time.sleep(0.1)
        request = api.create_request()
        request.get_player(
            player_locale=args.player_locale)
        request.call()

    if 7 not in tutorial_state:
        time.sleep(random.uniform(4, 10))
        request = api.create_request()
        request.mark_tutorial_complete(tutorials_completed=7)
        log.debug('Sending 7 tutorials_completed for %s.', account['username'])
        request.call()

    if starter_id:
        time.sleep(random.uniform(3, 5))
        request = api.create_request()
        request.set_buddy_pokemon(pokemon_id=starter_id)
        log.debug('Setting buddy pokemon for %s.', account['username'])
        request.call()
        time.sleep(random.uniform(0.8, 1.8))

    # Sleeping before we start scanning to avoid Niantic throttling.
    log.debug('And %s is done. Wait for a second, to avoid throttle.',
              account['username'])
    time.sleep(random.uniform(2, 4))
    return True


# Complete tutorial with a level up by a Pokestop spin.
# API argument needs to be a logged in API instance.
# Called during fort parsing in models.py
def tutorial_pokestop_spin(api, player_level, forts, step_location, account):
    if player_level > 1:
        log.debug(
            'No need to spin a Pokestop. ' +
            'Account %s is already level %d.',
            account['username'], player_level)
    else:  # Account needs to spin a Pokestop for level 2.
        log.debug(
            'Spinning Pokestop for account %s.',
            account['username'])
        for fort in forts:
            if fort.get('type') == 1:
                if spin_pokestop(api, fort, step_location, account):
                    log.debug(
                        'Account %s successfully spun a Pokestop ' +
                        'after completed tutorial.',
                        account['username'])
                    return True

    return False


def get_player_stats(response_dict):
    inventory_items = response_dict.get('responses', {})\
        .get('GET_INVENTORY', {}).get('inventory_delta', {})\
        .get('inventory_items', [])
    for item in inventory_items:
        item_data = item.get('inventory_item_data', {})
        if 'player_stats' in item_data:
            return item_data['player_stats']
    return {}


def get_player_inventory(map_dict):
    inventory_items = map_dict['responses'].get(
        'GET_INVENTORY', {}).get(
        'inventory_delta', {}).get(
        'inventory_items', [])
    inventory = {}
    no_item_ids = (
        ITEM_UNKNOWN,
        ITEM_TROY_DISK,
        ITEM_X_ATTACK,
        ITEM_X_DEFENSE,
        ITEM_X_MIRACLE,
        ITEM_POKEMON_STORAGE_UPGRADE,
        ITEM_ITEM_STORAGE_UPGRADE
    )
    for item in inventory_items:
        iid = item.get('inventory_item_data', {})
        if 'item' in iid and iid['item']['item_id'] not in no_item_ids:
            item_id = iid['item']['item_id']
            count = iid['item'].get('count', 0)
            inventory[item_id] = count
        elif 'egg_incubators' in iid and 'egg_incubator' in iid['egg_incubators']:
            for incubator in iid['egg_incubators']['egg_incubator']:
                item_id = incubator['item_id']
                inventory[item_id] = inventory.get(item_id, 0) + 1
    return inventory


def spin_pokestop(api, fort, step_location, account):
    spinning_radius = 0.04
    if in_radius((fort['latitude'], fort['longitude']), step_location,
                 spinning_radius):
        log.debug('Attempt to spin Pokestop (ID %s)', fort['id'])

        time.sleep(random.uniform(0.8, 1.8))  # Do not let Niantic throttle
        spin_response = spin_pokestop_request(api, fort, step_location, account)
        time.sleep(random.uniform(2, 4))  # Do not let Niantic throttle

        # Check for reCaptcha
        captcha_url = spin_response['responses'][
            'CHECK_CHALLENGE']['challenge_url']
        if len(captcha_url) > 1:
            log.debug('Account encountered a reCaptcha.')
            return False

        spin_result = spin_response['responses']['FORT_SEARCH']['result']
        if spin_result is 1:
            log.debug('Successful Pokestop spin.')
            return True
        elif spin_result is 2:
            log.debug('Pokestop was not in range to spin.')
        elif spin_result is 3:
            log.debug('Failed to spin Pokestop. Has recently been spun.')
        elif spin_result is 4:
            log.debug('Failed to spin Pokestop. Inventory is full.')
        elif spin_result is 5:
            log.debug('Maximum number of Pokestops spun for this day.')
        else:
            log.debug(
                'Failed to spin a Pokestop. Unknown result %d.',
                spin_result)

    return False


def spin_pokestop_request(api, fort, step_location, account):
    try:
        req = api.create_request()
        req.fort_search(
            fort_id=fort['id'],
            fort_latitude=fort['latitude'],
            fort_longitude=fort['longitude'],
            player_latitude=step_location[0],
            player_longitude=step_location[1])
        req.check_challenge()
        req.get_hatched_eggs()
        add_get_inventory_request(req, account)
        req.check_awarded_badges()
        req.download_settings()
        req.get_buddy_walked()
        spin_pokestop_response = req.call()

        update_account_from_response(account, spin_pokestop_response)

        return spin_pokestop_response

    except Exception as e:
        log.error('Exception while spinning Pokestop: %s.', repr(e))
        return False


def encounter_pokemon_request(api, account, encounter_id, spawnpoint_id,
                              scan_location):
    try:
        # Setup encounter request envelope.
        req = api.create_request()
        req.encounter(
            encounter_id=encounter_id,
            spawn_point_id=spawnpoint_id,
            player_latitude=scan_location[0],
            player_longitude=scan_location[1])
        req.check_challenge()
        req.get_hatched_eggs()
        add_get_inventory_request(req, account)
        req.check_awarded_badges()
        req.get_buddy_walked()
        response = req.call()

        update_account_from_response(account, response)
        return response

    except Exception as e:
        log.error('Exception while encountering Pokémon: %s.', repr(e))
        return False


def update_inventory_totals(inventory):
    ball_ids = [
        ITEM_POKE_BALL,
        ITEM_GREAT_BALL,
        ITEM_ULTRA_BALL,
        ITEM_MASTER_BALL
    ]
    balls = 0
    total_items = 0
    for item_id in inventory:
        if item_id in ['total', 'balls']:
            continue
        if item_id in ball_ids:
            balls += inventory[item_id]
        total_items += inventory[item_id]
    inventory['balls'] = balls
    inventory['total'] = total_items


def update_account_from_response(account, response):
    # Set an (empty) inventory if necessary
    if not 'inventory' in account or account['inventory'] is None:
        account['inventory'] = {}

    # Update inventory (balls, items)
    inventory_update = get_player_inventory(response)
    account['inventory'].update(inventory_update)
    update_inventory_totals(account['inventory'])

    # Update stats (level, xp, encounters, captures, km walked, etc.)
    account.update(get_player_stats(response))

    # Check if rare/shadowed Pokemon are found
    if 'GET_MAP_OBJECTS' in response.get('responses', {}):
        if sees_shadowed_pokemon(response):
            account['scans_without_rares'] = 0
        else:
            account['scans_without_rares'] = (account.get(
                'scans_without_rares') or 0) + 1

    # Update last timestamp for inventory requests
    account['last_timestamp_ms'] = get_new_api_timestamp(response)


def add_get_inventory_request(request, account):
    if account.get('last_timestamp_ms'):
        request.get_inventory(last_timestamp_ms=account['last_timestamp_ms'])
    else:
        request.get_inventory()


# The AccountSet returns a scheduler that cycles through different
# sets of accounts (e.g. L30). Each set is defined at runtime, and is
# (currently) used to separate regular accounts from L30 accounts.
# TODO: Migrate the old account Queue to a real AccountScheduler, preferably
# handled globally via database instead of per instance.
# TODO: Accounts in the AccountSet are exempt from things like the
# account recycler thread. We could've hardcoded support into it, but that
# would have added to the amount of ugly code. Instead, we keep it as is
# until we have a proper account manager.
class AccountSet(object):

    def __init__(self, kph):
        self.sets = {}

        # Scanning limits.
        self.kph = kph

        # Thread safety.
        self.next_lock = Lock()

    # Set manipulation.
    def create_set(self, name, values=[]):
        if name in self.sets:
            raise Exception('Account set ' + name + ' is being created twice.')

        self.sets[name] = values

    # Release an account back to the pool after it was used.
    def release(self, account):
        if 'in_use' not in account:
            log.error('Released account %s back to the AccountSet,'
                      + " but it wasn't locked.",
                      account['username'])
        else:
            account['in_use'] = False

    # Get next account that is ready to be used for scanning.
    def next(self, set_name, coords_to_scan):
        # Yay for thread safety.
        with self.next_lock:
            # Readability.
            account_set = self.sets[set_name]

            # Loop all accounts for a good one.
            now = default_timer()
            max_speed_kmph = self.kph

            for i in range(len(account_set)):
                account = account_set[i]

                # Make sure it's not in use.
                if account.get('in_use', False):
                    continue

                # Make sure it's not captcha'd.
                if account.get('captcha', False):
                    continue

                # Check if we're below speed limit for account.
                last_scanned = account.get('last_scanned', False)

                if last_scanned:
                    seconds_passed = now - last_scanned
                    old_coords = account.get('last_coords', coords_to_scan)

                    distance_km = equi_rect_distance(
                        old_coords,
                        coords_to_scan)
                    cooldown_time_sec = distance_km / max_speed_kmph * 3600

                    # Not enough time has passed for this one.
                    if seconds_passed < cooldown_time_sec:
                        continue

                # We've found an account that's ready.
                account['last_scanned'] = now
                account['last_coords'] = coords_to_scan
                account['in_use'] = True

                return account

        # TODO: Instead of returning False, return the amount of min. seconds
        # the instance needs to wait until the first account becomes available,
        # so it doesn't need to keep asking if we know we need to wait.
        return False
