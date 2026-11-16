"""Local interface translations; user data and internal menu keys stay unchanged."""
import re
import weakref
import tkinter as tk
import customtkinter as ct

LANGUAGES={'Русский':'ru','English':'en'}
current='ru'
_widgets=weakref.WeakKeyDictionary()
_installed=False
EN={
 'Главная':'Home','Моды':'Mods','Сборки':'Modpacks','Ресурспаки':'Resource packs','Шейдеры':'Shaders','Аккаунты':'Accounts','Настройки':'Settings',
 'С возвращением в свой мир!':'Welcome back to your world!','Добро пожаловать':'Welcome','в TUL4N':'to TUL4N','Твой мир. Твои правила.':'Your world. Your rules.',
 'Играть':'Play','Готов к новому приключению':'Ready for a new adventure','Офлайн-профиль':'Offline profile','Выберите ник':'Choose a nickname',
 'Отменить загрузку':'Cancel download','Повторить':'Retry','Журнал запуска':'Launch log','Восстановить файлы':'Repair game files',
 'Твой профиль':'Your profile','Выбери ник для следующего приключения':'Choose a nickname for your next adventure','Выбрать':'Select',
 'Создать аккаунт':'Create account','Ник игрока':'Player nickname','3–16 символов: латинские буквы, цифры, _':'3–16 characters: Latin letters, digits, _',
 'Настрой под себя':'Make it yours','Язык интерфейса / Interface language':'Язык интерфейса / Interface language','Оформление':'Appearance',
 'Путь к java.exe • оставьте пустым для автоматического выбора':'Path to java.exe • leave empty for automatic selection','Память игры, ГБ':'Game memory, GB',
 'Магазин модов • Modrinth':'Mod store • Modrinth','Поиск и скачивание доступны без аккаунта и API-ключа.':'Search and downloads need no account or API key.',
 'Сохранить настройки':'Save settings','Настройки сохранены':'Settings saved','Проверить обновления':'Check for updates','Загрузить обновление':'Download update',
 'Основной цвет':'Accent color','Цвет кнопок':'Button color','Выделенные элементы':'Selected items','Панели и карточки':'Panels and cards','Палитра':'Palette',
 'Классический':'Classic','Мягкий':'Soft','Контрастный':'High contrast','Исходные углы':'Default corners','Стандартные':'Standard','Компактные':'Compact',
 'Непрозрачность окна':'Window opacity','Предпросмотр • TUL4N':'Preview • TUL4N','Изменения сразу видны во всём лаунчере.':'Changes apply throughout the launcher immediately.',
 'Пример кнопки':'Example button','Сбросить оформление':'Reset appearance','HEX: #RRGGBB. Цвета сохраняются автоматически.':'HEX: #RRGGBB. Colors are saved automatically.',
 'Изумрудная':'Emerald','Голубая':'Sky blue','Синяя':'Blue','Фиолетовая':'Purple','Красная':'Red','Оранжевая':'Orange','Розовая':'Pink','Золотая':'Gold','Бирюзовая':'Turquoise','Чёрно-белая':'Monochrome',
 'Синий':'Blue','Голубой':'Sky blue','Черный':'Black','Белый':'White','Фиолетовый':'Purple','Зеленый':'Green','Красный':'Red',
 'Каталог':'Catalog','Установленные':'Installed','Мои сборки':'My modpacks','Импорт по коду':'Import code','Название мода...':'Mod name...',
 'Название новой сборки':'New modpack name','Поиск модов: sodium, jei, create...':'Search mods: sodium, jei, create...',
 'Все категории':'All categories','По релевантности':'Relevance','По загрузкам':'Downloads','Сначала новые':'Newest','По обновлению':'Updated',
 'Приключения':'Adventure','Технологии':'Technology','Магия':'Magic','Оптимизация':'Optimization','Лёгкие':'Lightweight','Квесты':'Quests',
 'Скачать':'Download','Страница':'Page','Подробнее':'Details','Установить':'Install','Удалить':'Remove','Отключить':'Disable','Включить':'Enable',
 'Папка':'Folder','Управление':'Manage','Экспортировать':'Export','Импортировать':'Import','Импортировать сборку из файла':'Import modpack file',
 'Как поделиться сборкой?':'How do you want to share this modpack?','Код TUL4N':'TUL4N code','Файл сборки (.tul4n.zip)':'Modpack file (.tul4n.zip)',
 'Код скачает те же версии компонентов с Modrinth.':'The code downloads the same component versions from Modrinth.',
 'Архив с модами, настройками, ресурспаками, шейдерами и обложкой.\nБез миров, аккаунтов и файлов самой игры.':'Archive with mods, settings, resource packs, shaders and cover.\nWorlds, accounts and game files are excluded.',
 'Проверить моды':'Check mods','Обновить моды':'Update mods','Откатить моды':'Roll back mods','Копия миров':'Copy worlds','Сохранить параметры':'Save options',
 'Экспортировать файл (.tul4n.zip)':'Export file (.tul4n.zip)','Проверить и восстановить Minecraft':'Verify and repair Minecraft','Отменить текущую загрузку':'Cancel current download','Открыть папку и журналы':'Open folder and logs',
 'Память, ГБ':'Memory, GB','Ширина окна':'Window width','Высота окна':'Window height','Полный экран':'Fullscreen',
 'Настройки применяются только к этой сборке':'These options apply only to this modpack','Путь Java • пусто = автоматически':'Java path • empty = automatic',
 'Дополнительные параметры Java • значения через «=»':'Extra Java arguments • use «=» for values','Закрывать лаунчер после успешного запуска игры':'Close launcher after starting the game',
 'Копировать миры перед изменением модов':'Copy worlds before changing mods','Только ошибки':'Errors only','Обновлять':'Auto refresh','Обновить сейчас':'Refresh now',
 'Скопировать ошибки':'Copy errors','Скопировать журнал':'Copy log','Вывод запуска':'Launch output','Журнал Minecraft':'Minecraft log','Последний crash-report':'Latest crash report',
 'Показываются последние 512 КБ. Токены и пароли скрываются.':'Shows the latest 512 KB. Tokens and passwords are hidden.',
 'Скопировано. Токены и пароли скрыты.':'Copied. Tokens and passwords are hidden.','Создать':'Create','Создать сборку':'Create modpack',
 'Сохранить':'Save','Отмена':'Cancel','Закрыть':'Close','Назад':'Back','Далее':'Next','Поиск':'Search','Найти':'Search',
 'Описание':'Description','Обложка':'Cover','Выбрать обложку':'Choose cover','Удалить обложку':'Remove cover','Сохранить оформление':'Save presentation',
 'Скопировать код':'Copy code','Сохранить код':'Save code','Вставить код':'Paste code','Проверить код':'Check code','Импортировать сборку':'Import modpack',
 'Избранное':'Favorites','Все':'All','Установить Iris':'Install Iris','Проверить обновления ресурсов':'Check resource updates',
 'Сначала закройте игру и дождитесь завершения операции.':'Close the game and wait for the current operation to finish.',
 'Выбрать сборку':'Select modpack','Название сборки':'Modpack name','Загрузка сборок…':'Loading modpacks…','Проверка…':'Checking…',
 'МОДЫ':'MODS','СБОРКИ':'MODPACKS','РЕСУРСПАКИ':'RESOURCE PACKS','ШЕЙДЕРЫ':'SHADERS','Ресурспак':'Resource pack','Шейдер':'Shader',
 'Цвет TUL4N':'TUL4N color','Цветовая схема':'Color theme','Генерация мира':'World generation','Утилиты':'Utilities','По популярности':'Popularity',
 'Modrinth • поиск и установка в выбранную сборку':'Modrinth • search and install into the selected modpack',
 'Поиск модов: sodium, jei, create…':'Search mods: sodium, jei, create…','Поиск сборок…':'Search modpacks…','Поиск…':'Searching…',
 'Найти моды':'Find mods','Популярные':'Popular','Найти сборки':'Find modpacks','Сборка:':'Modpack:','Сборка: ':'Modpack: ',
 'Твоя личность':'Your identity','Создайте профиль':'Create a profile','Выберите готовую сборку Modrinth или создайте свою.':'Choose a Modrinth modpack or create your own.',
 'Офлайн-аккаунт содержит только ник. Он подходит для одиночной игры\nи серверов, разрешающих офлайн-подключения.':'An offline account contains only a nickname. Use it for singleplayer\nand servers that allow offline connections.',
 'Введите название мода или откройте популярные.':'Enter a mod name or browse popular mods.','Введите название или найдите популярные проекты.':'Enter a name or browse popular projects.',
 'Поделиться кодом':'Share code','Создать код':'Create code','Сохранить код в файл':'Save code to file','Загрузить код из файла':'Load code from file',
 'Подтвердить импорт':'Confirm import','Повторить проверку':'Retry verification','Повторить неудачный этап':'Retry failed step','Создать отдельную копию':'Create a separate copy','Указать другое название':'Use another name',
 'Установить в сборку:':'Install into modpack:','Существующие сборки останутся без изменений.':'Existing modpacks will remain unchanged.',
 'Вставьте полный код. Он содержит состав сборки, а не JAR/ZIP-файлы.\nMinecraft, загрузчик и точные файлы будут скачаны автоматически.':'Paste the complete code. It lists components instead of containing JAR/ZIP files.\nMinecraft, its loader and exact component files will be downloaded automatically.',
 'Выберите файлы. Неизвестные Modrinth файлы нужно исключить.\nМиры, кэш, логи, аккаунты и личные настройки не экспортируются.':'Select files. Files unknown to Modrinth must be excluded.\nWorlds, caches, logs, accounts and personal settings are excluded.',
 'Автопроверка при запуске и каждые 5 часов':'Checks at startup and every 5 hours','Установлена последняя версия':'You have the latest version','Проверяем обновления…':'Checking for updates…','Скачиваем обновление…':'Downloading update…',
 'Автор не указал список изменений.':'The author has not provided a changelog.','Вернуть предыдущую версию':'Restore previous version','Установить показанные версии':'Install listed versions',
 'Готово':'Done','Скопировано':'Copied','Стр. 1 из 1':'Page 1 of 1','Далее ▸':'Next ▸','◂ Назад':'◂ Back',
 'Убрать из избранного':'Remove from favorites','Убрать обложку':'Remove cover','активен':'active','не активен':'inactive','не выбрана':'not selected','не установлен':'not installed',
 'Журнал пока не создан. Запустите игру.':'No log yet. Start the game.','Строк с ошибками в доступной части журнала не найдено.':'No error lines found in the available log.',
 'Для использования шейдера установите совместимый Iris или OptiFine. ZIP скачается в shaderpacks.':'Install a compatible Iris or OptiFine to use shaders. The ZIP will be saved to shaderpacks.',
}

def tr(value):
    if current!='en' or not isinstance(value,str):return value
    if value in EN:return EN[value]
    # Preserve navigation icons/checkmarks, not the internal Russian action keys.
    match=re.fullmatch(r'([^А-Яа-яЁё]*)([А-Яа-яЁё].*?)\s*',value)
    if match and match[2] in EN:return match[1]+EN[match[2]]
    return value

def select(language):
    global current
    current=language if language in ('ru','en') else 'ru'
    for widget,options in list(_widgets.items()):
        try:
            if widget.winfo_exists():widget.configure(**options)
        except tk.TclError:pass

def install():
    global _installed
    if _installed:return
    _installed=True
    for cls in (ct.CTkLabel,ct.CTkButton,ct.CTkEntry,ct.CTkSwitch,ct.CTkCheckBox):
        init,configure=cls.__init__,cls.configure
        def translated_init(self,*args,_init=init,**kwargs):
            options={k:v for k,v in kwargs.items() if k in ('text','placeholder_text')}
            _widgets[self]=options;kwargs.update({k:tr(v) for k,v in options.items()});_init(self,*args,**kwargs)
        def translated_configure(self,*args,_configure=configure,**kwargs):
            options={k:v for k,v in kwargs.items() if k in ('text','placeholder_text')}
            _widgets.setdefault(self,{}).update(options);kwargs.update({k:tr(v) for k,v in options.items()})
            return _configure(self,*args,**kwargs)
        cls.__init__,cls.configure=translated_init,translated_configure

