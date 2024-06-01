import json
import os.path
import time

import requests
import urllib3.exceptions as u_exceptions
from loguru import logger
from notifiers.logging import NotificationHandler

import config


BAD_WORKERS_FILE = 'bad_workers.json'


def log_setup():
    logger.add(
        'log',
        level='INFO',
        rotation='300 KB',
        compression='zip',
    )
    tg_handler = NotificationHandler('telegram', defaults=config.telegram_params)
    logger.add(tg_handler, level='ERROR', format='{time:HH:mm} - Mine monitor - {message}')


def get_response_in_json(api_address, tries=3, sleep_between_tries_in_sec=5*60):
    last_error = None
    for attempt in range(tries):
        try:
            return requests.get(api_address).json()
        except Exception as err:
            last_error = err
            logger.info(f"Can't get url response. Error - {err}")
            if attempt < tries - 1:
                time.sleep(sleep_between_tries_in_sec)
    log_error(last_error, tries)


def log_error(last_error, tries):
    if isinstance(last_error, (ConnectionError, u_exceptions.NewConnectionError)):
        logger.error(f"Can't get url response after {tries} tries. Error - {type(last_error).__name__}")
    else:
        logger.error(f"Can't get json response after {tries} tries. Error - {last_error}")


def load_bad_workers(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
    return {}


def save_bad_workers(file_path, bad_workers):
    with open(file_path, 'w') as file:
        json.dump(bad_workers, file, indent=4)


def main():
    log_setup()
    coins = config.miners
    bad_workers = load_bad_workers(BAD_WORKERS_FILE)
    workers_state = {}
    for coin_name, coin_info in coins.items():
        workers = coin_info['workers']
        site = coin_info['site']
        address = coin_info['address']
        coin_workers_state = check_coin_miners(workers, site, address, coin_name)
        workers_state.update(coin_workers_state)
    new_bad_workers = compare_current_and_last_bad_workers(bad_workers, workers_state)
    save_bad_workers(BAD_WORKERS_FILE, new_bad_workers)


def compare_current_and_last_bad_workers(bad_workers, current_workers):
    upped_workers = []
    downed_workers = []
    for coin, workers in current_workers.items():
        if coin not in bad_workers:
            # If bad_workers.json not exist or if we add new coin,
            # we must create key of the dict with empty list.
            bad_workers[coin] = []
        for worker_name, hashrate in workers.items():
            # The special value -1 is intended to filter out workers
            # who are not currently receiving statistics from the site.
            if hashrate == -1:
                continue
            if hashrate == 0 and worker_name not in bad_workers[coin]:
                downed_workers.append(f'{coin}:{worker_name}')
                bad_workers[coin].append(worker_name)
            elif hashrate > 0 and worker_name in bad_workers[coin]:
                upped_workers.append(f'{coin}:{worker_name}')
                bad_workers[coin].remove(worker_name)
    log_changed_status(upped_workers, downed_workers)
    return bad_workers


def log_changed_status(upped_workers, downed_workers):
    if upped_workers:
        logger.error(f'These workers are back online: {' '.join(upped_workers)}')
    if downed_workers:
        logger.error(f'These workers are offline: {' '.join(downed_workers)}')


def check_coin_miners(workers, site, address, coin):
    coin_workers_state = {coin: {}}
    api_address = f'{site}?address={address}'
    json_response = get_response_in_json(api_address)
    if json_response is None:
        for worker in workers:
            # Special value -1 is to filter these workers then compare current and last bad workers.
            coin_workers_state[coin][worker] = -1
        return coin_workers_state
    api_workers_info = json_response['workers']
    web_workers = {web_worker['name']: int(web_worker['hashrate_1h']) for web_worker in api_workers_info}
    for worker in workers:
        if worker not in web_workers:
            logger.error(f'Worker {worker} on {coin} is long time offline or never was online, change config.py')
            coin_workers_state[coin][worker] = 0
        else:
            coin_workers_state[coin][worker] = web_workers[worker]
    return coin_workers_state


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        logger.error(f'Unidentified error catch from main: {error}')
