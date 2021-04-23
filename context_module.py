from __future__ import annotations
from abc import ABC, abstractmethod

from alice_module import *
from conditions import CONDITIONS
import re
import logging
from dotenv import load_dotenv
import requests
import os

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)
logging.basicConfig(
    filename='logs.log',
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
    level=logging.DEBUG
)

SCAN_WORDS = {'проверь', 'просканируй', 'сканируй', 'проверить', 'просканировать', 'сканировать', 'ссылка'}
EXIT_WORDS = {'выход', 'пока', 'выйти', 'уйти', 'покинуть'}
CHOICE_WORDS = {'функция', 'функции', 'возможности', 'возможность', 'варианты', 'вариант',
                'модули', 'модуль', 'умеешь'}
SKILLS_WORDS = {'переводчик', 'сканер', 'погода'}
THANKS_WORDS = {'спасибо', 'класс', 'круто'}
TRANSLATE_WORDS = {'переведи', 'переведите', 'перевод'}

API_KEY = os.getenv('API_KEY')
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
GEOCODER_API_KEY = os.getenv('GEOCODER_API_KEY')
VT_URL = 'https://www.virustotal.com/api/v3/urls'


class Context:
    """Класс Context предназначен для управления состояниями навыка Алисы.
    ---------------------------------------------------------------------
    Методы
        transition_to(state) - переключает контекст в состояние state

        handle_dialog(res, req) - основная функция для управления диалогом с пользователем.
            res: AliceResponse - ответ для пользователя в виде класса AliceResponse
            req: AliceRequest - запрос пользователя в виде класса AliceRequest"""
    _state = None

    def __init__(self, state):
        self.transition_to(state)

    def transition_to(self, state):
        logging.info(f'Context: переключаемся в {type(state).__name__}')
        self._state = state
        self._state.context = self

    def handle_dialog(self, res: AliceResponse, req: AliceRequest):
        self._state.handle_dialog(res, req)


class State(ABC):
    """Базовый абстрактный класс состояния.
     --------------------------------------
     Методы
        context - возвращает используемый данным состоянием контекст
        handle_dialog(res: req) - функция, которую вызывает контекст, для обработки диалога
        с пользователем"""

    @property
    def context(self) -> Context:
        return self._context

    @context.setter
    def context(self, context: Context) -> None:
        self._context = context

    @abstractmethod
    def handle_dialog(self, res: AliceResponse, req: AliceRequest):
        pass


class ScanUrlState(State):
    """
    Реализация класса сканирования для удобной работы с VirusTotal API
    """

    def handle_dialog(self, res: AliceResponse, req: AliceRequest) -> None:
        try:
            if set(req.words).intersection(EXIT_WORDS):
                res.set_answer('Пока :)')
                self.context.transition_to(ExitState())
            if set(req.words).intersection(THANKS_WORDS):
                res.set_answer('Ага, не за что :)')
            if self.__check_url_regex(req.request_string):
                result = self.scan(req.request_string)
                if result:
                    res.set_answer(result)
                else:
                    raise UserWarning
            elif set(req.words).intersection(SCAN_WORDS):
                cleaned_request = self.__delete_unnecessary_words(req.words)
                if cleaned_request:
                    result = self.scan(cleaned_request)
                    logging.info(result)
                    if result:
                        res.set_answer(result)
                    else:
                        raise UserWarning
                else:
                    raise UserWarning
            else:
                raise UserWarning
        except UserWarning:
            res.set_answer('Что-то не так, либо Вы не ввели ссылку, либо она неправильная. '
                           'Попробуйте еще раз, либо поменяйте ссылку ;)')

    def __delete_unnecessary_words(self, words: list) -> str or dict:
        for e in words:
            if self.__check_url_regex(e):
                return e
        return False

    @staticmethod
    def __check_url_regex(url: str) -> bool:
        pattern = '^((http|https):\\/\\/)?(www\\.)?([A-Za-zА-Яа-я0-9]' \
                  '{1}[A-Za-zА-Яа-я0-9\\-]*\\.?)*\\.{1}[A-Za-zА-Яа-я0-9-]{2,8}(\\/([\\w#!:.?+=&%@!\\-\\/])*)?'
        matches = re.match(pattern, url)
        if matches:
            return True
        return False

    @staticmethod
    def __get_url_id(url: str) -> str or bool:
        params = {'x-apikey': API_KEY}
        req = requests.post(VT_URL, headers=params, data=f'url={url}')
        if req.status_code == 200:
            url_id = req.json()['data']['id']
            return url_id
        return False

    @staticmethod
    def __get_info(url_id: str) -> dict or bool:
        params = {'x-apikey': API_KEY}
        response = requests.get(f'https://www.virustotal.com/api/v3/analyses/{url_id}', headers=params)
        logging.info(response.json())
        if response.status_code == 200:
            res = dict(response.json()['data']['attributes']['results'])
            results = dict()
            for e in res.keys():
                if res[e]['result'] in results.keys():
                    results[res[e]['result']] += 1
                else:
                    results[res[e]['result']] = 1
            logging.info(results)
            return results
        return False

    def scan(self, url: str) -> str or bool:
        url_id = self.__get_url_id(url)
        if url_id:
            info = self.__get_info(url_id)
            if info:
                comment = ''
                if len(set(info.keys()).intersection({'clean', 'unrated'})) == 2:
                    if info['unrated'] / info['clean'] >= 1.2:
                        comment = 'Какая-то странная ссылка, будь внимателен\n'
                    elif info['unrated'] / info['clean'] <= 0.1:
                        comment = 'Все классно, должно быть безопасно!\n'
                    else:
                        comment = 'Что-то странное 0_o\n'
                elif len(set(info.keys()).intersection({'clean', 'unrated'})) == 1:
                    if 'clean' in info.keys():
                        comment = 'Все классно, должно быть безопасно!\n'
                    if 'unrated' in info.keys():
                        comment = 'Что-то странное 0_o\n'
                else:
                    comment = 'Оу, братец, как-то подозрительно не думаю, что стоит переходить, ' \
                              'либо используй защиту!\n'
                return comment + f'''Отчет антивирусов: {' '.join([f"{e} = {info[e]}" for e in info.keys()])}'''
        return False


class TranslatorState(State):
    """Класс TranslatorState - одно из состояний навыка Алисы.
    ----------------------------------------------------------
    Note:
        Навык работает не со всеми языками, а только с самыми основными
        Навык по умолчанию переводит с любого языка на английский, если не указан язык,
         на который нужно перевести
        Запрос должен содержать в себе слово "переведи" для работы функции.
    ----------------------------------------------------------
    Задача класса - реализовывать  основные функции голосового переводчика:
        переводить по умолчанию с русского на английский
        переводить на необходимый язык при его указании ("переведи <предложение> на японский)
        переводить с необходимого языка при его указании (переведи <предложение> с японского)
        переводить с выбранного языка на другой язык (переведи <предложение> с японского на русский)
        определять только то, что нужно перевести, и не учитывать ненужные для перевода слова.
        определять стандартные ошибки при вводе пользователя
    --------------------------------------------------------------------------------------------
    Методы
        handle_dialog(res, req) - основная функция управления диалогом с пользователем
        get_translate_request(words, foreign_words) - возвращает строку, которую необходимо
            перевести, исходный язык, язык перевода и callback (ошибку или OK)
        __delete_unnecessary_words(words) - удаляет из списка слов пользователя ненужные для
            перевода слова.
        __get_languages(words) - определяет с какого языка и на какой язык пользователь хочет
            совершить перевод. Возвращает языки в формате ISO639-1. Если язык не поддерживается,
            возвращается None.Если языки не указаны, возвращает en, ru.
        __language_to_iso(language) - возвращает язык в формате ISO639-1.
        __delete_languages(words, lang_fr, lang_to) - удаляет все языки ненужные из запроса
            для перевода
        translate(text, language_from, language_to) - переводит текст (text) с языка
            language_from на язык language_to
    ---------------------------------------------------------------------------------------------"""

    def handle_dialog(self, res: AliceResponse, req: AliceRequest):
        if set(req.words).intersection(EXIT_WORDS):
            self.context.transition_to(HelloState())
            return

        if set(req.words).intersection(TRANSLATE_WORDS):
            translate_req, lang_fr, lang_to, callback = self.get_translate_request(req.words,
                                                                                   req.foreign_words)
            if callback == 'OK':
                res.set_answer(self.translate(translate_req, lang_fr, lang_to))
                return
            res.set_answer(callback)

    def get_translate_request(self, words: list, foreign_words: list):
        to_translate_words = self.__delete_unnecessary_words(words)
        language_from, language_to = self.__get_languages(words)
        if not language_from:
            return None, language_from, language_to, 'Извините.' \
                                                     ' Я пока не умею переводить с этого языка'
        if not language_to:
            return None, language_from, language_to, 'Извините.' \
                                                     ' Я пока не умею переводить на этот язык'
        to_translate_words = self.__delete_languages(to_translate_words, language_from, language_to)
        if not to_translate_words:
            to_translate_words = foreign_words
        if not to_translate_words:
            return None, language_from, language_to, 'Извините. Вы не ввели то, что нужно перевести.'
        if language_from == language_to:
            if foreign_words and language_from == language_to == 'ru':
                return None, language_from, language_to, 'Извините. Я пока не умею распознавать' \
                                                         ' языки.Укажите язык пожалуйста'
            return None, language_from, language_to, 'Извините. Укажите два разных языка пожалуйста'

        return ' '.join(to_translate_words), language_from, language_to, 'OK'

    @staticmethod
    def __delete_unnecessary_words(words: list) -> list:
        unnecessary_words = {'алиса', 'переведи', 'переведите', 'перевод', 'слово', 'слова',
                             'предложение', 'предложения'}
        to_translate_words = [word for word in words if word not in unnecessary_words]
        return to_translate_words

    def __get_languages(self, words: list):
        language_from = 'ru'
        language_to = 'en'

        for i in range(len(words)):
            if words[i] == 'с' and 'ского' in words[i + 1]:
                language_from = self.__language_to_iso(f"{words[i + 1][:-3]}ий".title())
            elif words[i] == 'на' and 'ский' in words[i + 1]:
                language_to = self.__language_to_iso(words[i + 1].title())

        return language_from, language_to

    @staticmethod
    def __language_to_iso(language) -> str or None:
        with open('languages.json', 'r') as json_file:
            languages_to_iso = json.load(json_file)
            try:
                return languages_to_iso[language]
            except KeyError:
                return None

    @staticmethod
    def __delete_languages(words: list, lang_fr, lang_to) -> list:
        with open('languages.json', 'r') as json_file:
            langs = json.load(json_file)

            fr_lang = [lang for lang, cd in langs.items() if cd == lang_fr][0][:-2].lower()
            language_from = f'с {fr_lang}ого'
            to_lang = [lang for lang, cd in langs.items() if cd == lang_to][0].lower()
            language_to = f'на {to_lang}'

            my_words = ' '.join(words)
            if f'{language_from} языка' in my_words:
                my_words = my_words.replace(f'{language_from} языка', '')
            elif language_from in my_words:
                my_words = my_words.replace(language_from, '')
            if f'{language_to} язык' in my_words:
                my_words = my_words.replace(f'{language_to} язык', '')
            elif language_to in my_words:
                my_words = my_words.replace(language_to, '')
        return my_words.split()

    @staticmethod
    def translate(text, language_from='ru', language_to='en'):
        url = "https://translated-mymemory---translation-memory.p.rapidapi.com/api/get"

        params = {"langpair": f"{language_from}|{language_to}", "q": text, "mt": "1",
                  "onlyprivate": "0"}

        headers = {
            'x-rapidapi-key': "69bdf32b4cmsh23d9e9126500c48p192dfdjsnde5efcc7ffd9",
            'x-rapidapi-host': "translated-mymemory---translation-memory.p.rapidapi.com"
        }

        response = requests.get(url, headers=headers, params=params).json()

        translated = response['responseData']['translatedText']
        if ''.join(translated.split()) == ''.join(text.split()):
            return 'Вы указали неверный язык, перевод невозможен.'
        return translated


class WeatherState(State):
    def handle_dialog(self, res: AliceResponse, req: AliceRequest):
        try:
            if set(req.words).intersection(THANKS_WORDS):
                res.set_answer('Ага, не за что :)')
            else:
                weather = self.__get_info(req)
                if weather:
                    res.set_answer(weather)
                else:
                    raise UserWarning
        except UserWarning:
            res.set_answer('Что-то вы делаете не так, либо пробуйте еще, либо измените ваш запрос.')

    @staticmethod
    def __string_for_geocoder(place_dict: dict) -> str or bool:
        if len(place_dict.keys()):
            return ' '.join([place_dict[key] for key in place_dict.keys()])
        return False

    def __get_info(self, req: AliceRequest) -> dict or bool:
        if req.geo_names:
            place_req = self.__string_for_geocoder(req.geo_names[0])
            coord = self.__get_coord(place_req)
            if coord:
                params = {'X-Yandex-API-Key': WEATHER_API_KEY}
                lat = coord['lat']
                lon = coord['lon']
                url = f'https://api.weather.yandex.ru/v2/forecast?lat={lat}&lon={lon}&extra=true'
                req = requests.get(url, headers=params)
                if req.status_code == 200:
                    now_temp = req.json()['fact']['temp']
                    feels_like = req.json()['fact']['feels_like']
                    cond = CONDITIONS[req.json()['fact']['condition']]
                    wind = req.json()['fact']['wind_speed']
                    yesterday = req.json()['yesterday']['temp']
                    return f'СЕГОДНЯ: температура: {now_temp}°C, ощущается как {feels_like}°C; условия: {cond}, ' \
                           f'ветер: {wind} м/с;\nЗАВТРА: температура: {yesterday}°C'
        return False

    @staticmethod
    def __get_coord(place: str) -> dict or bool:
        r = requests.get(f'https://geocode-maps.yandex.ru/1.x/?format=json&apikey={GEOCODER_API_KEY}&geocode={place}')
        if r.status_code == 200:
            json_data = r.json()
            coord = json_data['response']['GeoObjectCollection']['featureMember'][0]['GeoObject']['Point']['pos'].split()
            return {'lat': coord[1], 'lon': coord[0]}
        return False


class HelloState(State):
    def handle_dialog(self, res: AliceResponse, req: AliceRequest):
        res.set_answer('Привет. Мы сделали прикольный навык!')
        self.context.transition_to(ChoiceState())


class ChoiceState(State):
    def handle_dialog(self, res: AliceResponse, req: AliceRequest):
        if set(req.words).intersection(SKILLS_WORDS) == {'переводчик'}:
            self.context.transition_to(TranslatorState())
            res.set_answer('Хорошо, давай переводить!\n'
                           'Пиши: переведи [слово]')
        elif set(req.words).intersection(SKILLS_WORDS) == {'сканер'}:
            self.context.transition_to(ScanUrlState())
            res.set_answer('Хорошо, отправь ссылку на сканирование!')
        elif set(req.words).intersection(SKILLS_WORDS) == {'погода'}:
            self.context.transition_to(WeatherState())
            res.set_answer('Хорошо, пиши место, где надо узнать погоду!\n'
                           'Пиши: [место]')
        else:
            res.set_answer('У нас есть несколько функций: переводчик, сканер, погода. '
                           'Что хочешь попробовать?')


class ExitState(State):
    def handle_dialog(self, res: AliceResponse, req: AliceRequest):
        res.set_answer('Работа с навыком закончена :)')
        self.context.transition_to(HelloState())
