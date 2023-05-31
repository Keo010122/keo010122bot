import codecs
import locale
import pickle
import re
import time
from contextlib import suppress
from datetime import timedelta
from enum import Enum
from random import choice
from textwrap import fill
from typing import Generator

import pywikibot
from pywikibot import config, i18n
from pywikibot.backports import List
from pywikibot.bot import SingleSiteBot
from pywikibot.exceptions import EditConflictError, Error, HiddenKeyError
from pywikibot.tools.formatter import color_format


locale.setlocale(locale.LC_ALL, '')
logbook = {
    'fr': ('Wikipedia:Prise de décision/'
           'Accueil automatique des nouveaux par un robot/log'),
    'ga': 'Project:Log fáilte',
    'ja': '利用者:Alexbot/Welcomebotログ',
    'nl': 'Project:Logboek welkom',
    'no': 'Project:Velkomstlogg',
    'sd': 'Project:ڀليڪار دوڳي',
    'sq': 'Project:Tung log',
    'ur': 'Project:نوشتہ خوش آمدید',
    'zh': 'User:Welcomebot/欢迎日志',
    'commons': 'Project:Welcome log',
}
# The text for the welcome message (e.g. {{welcome}}) and %s at the end
# that is your signature (the bot has a random parameter to add different
# sign, so in this way it will change according to your parameters).
netext = {
    'commons': '{{subst:welcome}} %s',
    'wikipedia': {
        'am': '{{subst:Welcome}} %s',
        'vi': '{{subst:welcome3}} %s',
    },
}
# The page where the bot will report users with a possibly bad username.
report_page = {
    'commons': ("Project:Administrators'noticeboard/User problems/Usernames"
                'to be checked'),
    'wikipedia': {
        'am': 'User:Beria/Report',
    }
}
# The page where the bot reads the real-time bad words page
# (this parameter is optional).
bad_pag = {
    'commons': 'Project:Welcome log/Bad_names',
    'wikipedia': {
        'zh-yue': 'User:Welcomebot/badname',
    }
}

timeselected = ' ~~~~~'  # Defining the time used after the signature

# The text for reporting a possibly bad username
# e.g. *[[Talk_page:Username|Username]]).
report_text = {
    'commons': '\n*{{user3|%s}}' + timeselected,
    'wikipedia': {
        'zh': '\n*{{User|%s}}' + timeselected
    }
}
# Set where you load your list of signatures that the bot will load if you use
# the random argument (this parameter is optional).
random_sign = {
    'am': 'User:Beria/Signatures',
}
# The page where the bot reads the real-time whitelist page.
# (this parameter is optional).
whitelist_pg = {
    'ar': 'Project:سجل الترحيب/قائمة بيضاء',
    'en': 'User:Filnik/whitelist',
    'ga': 'Project:Log fáilte/Bánliosta',
    'it': 'Project:Benvenuto_Bot/Lista_Whitewords',
    'ru': 'Участник:LatitudeBot/Белый_список',
}

# Text after the {{welcome}} template, if you want to add something
# Default (en): nothing.
final_new_text_additions = {
    'it': '\n<!-- fine template di benvenuto -->',
    'zh': '<small>(via ~~~)</small>',
}

#
#
logpage_header = {
    '_default': '{|border="2" cellpadding="4" cellspacing="0" style="margin: '
                '0.5em 0.5em 0.5em 1em; padding: 0.5em; background: #bfcda5; '
                'border: 1px #b6fd2c solid; border-collapse: collapse; '
                'font-size: 95%;"',
    'no': '[[Kategori:Velkomstlogg|{{PAGENAME}}]]\n{| class="wikitable"',
    'it': '[[Categoria:Benvenuto log|{{subst:PAGENAME}}]]\n{|border="2" '
          'cellpadding="4" cellspacing="0" style="margin: 0.5em 0.5em 0.5em '
          '1em; padding: 0.5em; background: #bfcda5; border: 1px #b6fd2c '
          'solid; border-collapse: collapse; font-size: 95%;"'
}

# Ok, that's all. What is below, is the rest of code, now the code is fixed
# and it will run correctly in your project ;)
############################################################################


class Msg(Enum):

    """Enum for show_status method providing message header and color."""

    MSG = 'MSG', 'lightpurple'
    IGNORE = 'NoAct', 'lightaqua'
    MATCH = 'Match', 'lightgreen'
    SKIP = 'Skip', 'lightyellow'
    WARN = 'Warn', 'lightred'
    DONE = 'Done', 'lightblue'
    DEFAULT = 'MSG', 'lightpurple'


class FilenameNotSet(Error):

    """An exception indicating that a signature filename was not specified."""


class Global:

    """Container class for global settings."""

    attachEditCount = 1     # edit count that an user required to be welcomed
    dumpToLog = 15          # number of users that are required to add the log
    offset = None           # skip users newer than that timestamp
    timeoffset = 0          # skip users newer than # minutes
    recursive = True        # define if the Bot is recursive or not
    timeRecur = 3600        # how much time (sec.) the bot waits before restart
    makeWelcomeLog = True   # create the welcome log or not
    confirm = False         # should bot ask to add user to bad-username list
    welcomeAuto = False     # should bot welcome auto-created users
    filtBadName = False     # check if the username is ok or not
    randomSign = False      # should signature be random or not
    saveSignIndex = False   # should save the signature index or not
    signFileName = None     # File name, default: None
    defaultSign = ('~~~~')  # default signature
    queryLimit = 50         # number of users that the bot load to check
    quiet = False           # Users without contributions aren't displayed


class WelcomeBot(SingleSiteBot):

    """Bot to add welcome messages on User pages."""

    def __init__(self, **kwargs) -> None:
        """Initializer."""
        super().__init__(**kwargs)
        self.check_managed_sites()
        self.bname = {}

        self.welcomed_users = []
        self.log_name = i18n.translate(self.site, logbook)

        if not self.log_name:
            globalvar.makeWelcomeLog = False
        if globalvar.randomSign:
            self.defineSign(True)

    def check_managed_sites(self) -> None:
        """Check that site is managed by welcome.py."""
        # Raises KeyError if site is not in netext dict.
        site_netext = i18n.translate(self.site, netext)
        if site_netext is None:
            raise KeyError(
                'welcome.py is not localized for site {} in netext dict.'
                .format(self.site))
        self.welcome_text = site_netext

    def badNameFilter(self, name, force=False) -> bool:
        """Check for bad names."""
        if not globalvar.filtBadName:
            return False

        # initialize blacklist
        if not hasattr(self, '_blacklist') or force:
            elenco = [
                ' ano', ' anus', 'anal ', 'babies', 'baldracca', 'balle',
                'bastardo', 'bestiali', 'bestiale', 'bastarda', 'b.i.t.c.h.',
                'bitch', 'boobie', 'bordello', 'breast', 'cacata', 'cacca',
                'cachapera', 'cagata', 'cane', 'cazz', 'cazzo', 'cazzata',
                'chiavare', 'chiavata', 'chick', 'christ ', 'cristo',
                'clitoride', 'coione', 'cojdioonear', 'cojones', 'cojo',
                'coglione', 'coglioni', 'cornuto', 'cula', 'culatone',
                'culattone', 'culo', 'deficiente', 'deficente', 'dio', 'die ',
                'died ', 'ditalino', 'ejackulate', 'enculer', 'eroticunt',
                'fanculo', 'fellatio', 'fica ', 'ficken', 'figa', 'sfiga',
                'fottere', 'fotter', 'fottuto', 'fuck', 'f.u.c.k.', 'funkyass',
                'gay', 'hentai.com', 'horne', 'horney', 'virgin', 'hotties',
                'idiot', '@alice.it', 'incest', 'jesus', 'gesu', 'gesù',
                'kazzo', 'kill', 'leccaculo', 'lesbian', 'lesbica', 'lesbo',
                'masturbazione', 'masturbare', 'masturbo', 'merda', 'merdata',
                'merdoso', 'mignotta', 'minchia', 'minkia', 'minchione',
                'mona', 'nudo', 'nuda', 'nudi', 'oral', 'sex', 'orgasmso',
                'porc', 'pompa', 'pompino', 'porno', 'puttana', 'puzza',
                'puzzone', 'racchia', 'sborone', 'sborrone', 'sborata',
                'sborolata', 'sboro', 'scopata', 'scopare', 'scroto',
                'scrotum', 'sega', 'sesso', 'shit', 'shiz', 's.h.i.t.',
                'sadomaso', 'sodomist', 'stronzata', 'stronzo', 'succhiamelo',
                'succhiacazzi', 'testicol', 'troia', 'universetoday.net',
                'vaffanculo', 'vagina', 'vibrator', 'vacca', 'yiddiot',
                'zoccola',
            ]
            elenco_others = [
                '@', '.com', '.sex', '.org', '.uk', '.en', '.it', 'admin',
                'administrator', 'amministratore', '@yahoo.com', '@alice.com',
                'amministratrice', 'burocrate', 'checkuser', 'developer',
                'http://', 'jimbo', 'mediawiki', 'on wheals', 'on wheal',
                'on wheel', 'planante', 'razinger', 'sysop', 'troll', 'vandal',
                ' v.f. ', 'v. fighter', 'vandal f.', 'vandal fighter',
                'wales jimmy', 'wheels', 'wales', 'www.',
            ]

            # blacklist from wikipage
            badword_page = pywikibot.Page(self.site,
                                          i18n.translate(self.site,
                                                         bad_pag))
            list_loaded = []
            if badword_page.exists():
                pywikibot.output('\nLoading the bad words list from {}...'
                                 .format(self.site))
                list_loaded = load_word_function(badword_page.get())
            else:
                self.show_status(Msg.WARN)
                pywikibot.output("The bad word page doesn't exist!")
            self._blacklist = elenco + elenco_others + list_loaded
            del elenco, elenco_others, list_loaded

        if not hasattr(self, '_whitelist') or force:
            # initialize whitelist
            whitelist_default = ['emiliano']
            wtlpg = i18n.translate(self.site, whitelist_pg)
            list_white = []
            if wtlpg:
                whitelist_page = pywikibot.Page(self.site, wtlpg)
                if whitelist_page.exists():
                    pywikibot.output('\nLoading the whitelist from {}...'
                                     .format(self.site))
                    list_white = load_word_function(whitelist_page.get())
                else:
                    self.show_status(Msg.WARN)
                    pywikibot.output("The whitelist's page doesn't exist!")
            else:
                self.show_status(Msg.WARN)
                pywikibot.warning("The whitelist hasn't been set!")

            # Join the whitelist words.
            self._whitelist = list_white + whitelist_default
            del list_white, whitelist_default

        with suppress(UnicodeEncodeError):
            for wname in self._whitelist:
                if wname.lower() in str(name).lower():
                    name = name.lower().replace(wname.lower(), '')
                    for bname in self._blacklist:
                        self.bname[name] = bname
                        return bname.lower() in name.lower()
            for bname in self._blacklist:
                if bname.lower() in str(name).lower():  # bad name positive
                    self.bname[name] = bname
                    return True
        return False

    def collect_bad_accounts(self, name: str) -> None:
        """Add bad account to queue."""
        if globalvar.confirm:
            answer = pywikibot.input_choice(
                '{} may have an unwanted username, do you want to report '
                'this user?'
                .format(name), [('Yes', 'y'), ('No', 'n'), ('All', 'a')],
                'n', automatic_quit=False)
            if answer in ['a', 'all']:
                answer = 'y'
                globalvar.confirm = False
        else:
            answer = 'y'

        if answer.lower() in ['yes', 'y'] or not globalvar.confirm:
            self.show_status()
            pywikibot.output(
                '{} is possibly an unwanted username. It will be reported.'
                .format(name))
            if hasattr(self, '_BAQueue'):
                self._BAQueue.append(name)
            else:
                self._BAQueue = [name]

        if len(self._BAQueue) >= globalvar.dumpToLog:
            self.report_bad_account()

    def report_bad_account(self) -> None:
        """Report bad account."""
        rep_text = ''
        # name in queue is max, put detail to report page
        pywikibot.output('Updating badname accounts to report page...')
        rep_page = pywikibot.Page(self.site,
                                  i18n.translate(self.site,
                                                 report_page))
        if rep_page.exists():
            text_get = rep_page.get()
        else:
            text_get = ('This is a report page for the Bad-username, '
                        'please translate me. ~~~')
        pos = 0
        # The talk page includes "_" between the two names, in this way
        # replace them to " ".
        for usrna in self._BAQueue:
            username = pywikibot.url2link(usrna, self.site, self.site)
            n = re.compile(re.escape(username))
            y = n.search(text_get, pos)
            if y:
                pywikibot.output('{} is already in the report page.'
                                 .format(username))
            else:
                # Adding the log.
                rep_text += i18n.translate(self.site,
                                           report_text) % username
                if self.site.code == 'it':
                    rep_text = '%s%s}}' % (rep_text, self.bname[username])

        com = i18n.twtranslate(self.site, 'welcome-bad_username')
        if rep_text != '':
            rep_page.put(text_get + rep_text, summary=com, force=True,
                         minor=True)
            self.show_status(Msg.DONE)
            pywikibot.output('Reported')
        self.BAQueue = []

    def makelogpage(self):
        """Make log page."""
        if not globalvar.makeWelcomeLog or not self.welcomed_users:
            return

        if self.site.code == 'it':
            pattern = '%d/%m/%Y'
        else:
            pattern = '%Y/%m/%d'
        target = self.log_name + '/' + time.strftime(
            pattern, time.localtime(time.time()))

        log_page = pywikibot.Page(self.site, target)
        if log_page.exists():
            text = log_page.get()
        else:
            # make new log page
            self.show_status()
            pywikibot.output(
                'Log page is not exist, getting information for page creation')
            text = i18n.translate(self.site, logpage_header,
                                  fallback=i18n.DEFAULT_FALLBACK)
            text += '\n!' + self.site.namespace(2)
            text += '\n!' + str.capitalize(
                self.site.mediawiki_message('contribslink'))

        # Adding the log... (don't take care of the variable's name...).
        text += '\n'
        text += '\n'.join(
            '{{WLE|user=%s|contribs=%d}}' % (
                user.title(as_url=True, with_ns=False), user.editCount())
            for user in self.welcomed_users)

        # update log page.
        while True:
            try:
                log_page.put(text, i18n.twtranslate(self.site,
                                                    'welcome-updating'))
            except EditConflictError:
                pywikibot.output('An edit conflict has occurred. Pausing for '
                                 '10 seconds before continuing.')
                time.sleep(10)
            else:
                break
        self.welcomed_users = []

    @property
    def generator(self) -> Generator[pywikibot.User, None, None]:
        """Retrieve new users."""
        while True:
            if globalvar.timeoffset != 0:
                start = self.site.server_time() - timedelta(
                    minutes=globalvar.timeoffset)
            else:
                start = globalvar.offset
            for ue in self.site.logevents('newusers',
                                          total=globalvar.queryLimit,
                                          start=start):
                if ue.action() == 'create' \
                   or ue.action() == 'autocreate' and globalvar.welcomeAuto:
                    try:
                        user = ue.page()
                    except HiddenKeyError:
                        pywikibot.exception()
                    else:
                        yield user

            self.write_log()
            if not globalvar.recursive:
                break

            # Wait some seconds and repeat retrieving new users
            self.show_status()
            strfstr = time.strftime('%d %b %Y %H:%M:%S (UTC)', time.gmtime())
            pywikibot.output('Sleeping {} seconds before rerun. {}'
                             .format(globalvar.timeRecur, strfstr))
            pywikibot.sleep(globalvar.timeRecur)

    def defineSign(self, force=False) -> List[str]:
        """Setup signature."""
        if hasattr(self, '_randomSignature') and not force:
            return self._randomSignature

        sign_text = ''
        creg = re.compile(r'^\* ?(.*?)$', re.M)
        if not globalvar.signFileName:
            sign_page_name = i18n.translate(self.site, random_sign)
            if not sign_page_name:
                self.show_status(Msg.WARN)
                pywikibot.output(
                    "{} doesn't allow random signature, force disable."
                    .format(self.site))
                globalvar.randomSign = False
                return None

            sign_page = pywikibot.Page(self.site, sign_page_name)
            if sign_page.exists():
                pywikibot.output('Loading signature list...')
                sign_text = sign_page.get()
            else:
                pywikibot.output('The signature list page does not exist, '
                                 'random signature will be disabled.')
                globalvar.randomSign = False
        else:
            try:
                f = codecs.open(
                    pywikibot.config.datafilepath(globalvar.signFileName), 'r',
                    encoding=config.console_encoding)
            except LookupError:
                f = codecs.open(pywikibot.config.datafilepath(
                    globalvar.signFileName), 'r', encoding='utf-8')
            except IOError:
                pywikibot.error('No fileName!')
                raise FilenameNotSet('No signature filename specified.')

            sign_text = f.read()
            f.close()
        self._randomSignature = creg.findall(sign_text)
        return self._randomSignature

    def skip_page(self, user) -> bool:
        """Check whether the user is to be skipped."""
        if user.isBlocked():
            self.show_status(Msg.SKIP)
            pywikibot.output('{} has been blocked!'.format(user.username))

        elif 'bot' in user.groups():
            self.show_status(Msg.SKIP)
            pywikibot.output('{} is a bot!'.format(user.username))

        elif 'bot' in user.username.lower():
            self.show_status(Msg.SKIP)
            pywikibot.output('{} might be a global bot!'
                             .format(user.username))

        elif user.editCount() < globalvar.attachEditCount:
            if not user.editCount() == 0:
                self.show_status(Msg.IGNORE)
                pywikibot.output('{} has only {} contributions.'
                                 .format(user.username, user.editCount()))
            elif not globalvar.quiet:
                self.show_status(Msg.IGNORE)
                pywikibot.output('{} has no contributions.'
                                 .format(user.username))
        else:
            return super().skip_page(user)

        return True

    def treat(self, user) -> None:
        """Run the bot."""
        self.show_status(Msg.MATCH)
        pywikibot.output('{} has enough edits to be welcomed.'
                         .format(user.username))
        ustp = user.getUserTalkPage()
        if ustp.exists():
            self.show_status(Msg.SKIP)
            pywikibot.output('{} has been already welcomed.'
                             .format(user.username))
            return

        if self.badNameFilter(user.username):
            self.collect_bad_accounts(user.username)
            return

        welcome_text = self.welcome_text
        if globalvar.randomSign:
            if self.site.family.name != 'wikinews':
                welcome_text = welcome_text % choice(self.defineSign())
            if self.site.sitename != 'wiktionary:it':
                welcome_text += timeselected
        elif self.site.sitename != 'wikinews:it':
            welcome_text = welcome_text % globalvar.defaultSign

        final_text = i18n.translate(self.site, final_new_text_additions)
        if final_text:
            welcome_text += final_text
        welcome_comment = i18n.twtranslate(self.site, 'welcome-welcome')
        try:
            # append welcomed, welcome_count++
            ustp.put(welcome_text, welcome_comment, minor=False)
        except EditConflictError:
            self.show_status(Msg.WARN)
            pywikibot.output(
                'An edit conflict has occurred, skipping this user.')
        else:
            self.welcomed_users.append(user)

        welcomed_count = len(self.welcomed_users)
        if globalvar.makeWelcomeLog:
            self.show_status(Msg.DONE)
            if welcomed_count == 0:
                count = 'No users have'
            elif welcomed_count == 1:
                count = 'One user has'
            else:
                count = '{} users have'.format(welcomed_count)
            pywikibot.output(count + ' been welcomed.')

            if welcomed_count >= globalvar.dumpToLog:
                self.makelogpage()

    def write_log(self):
        """Write logfile."""
        welcomed_count = len(self.welcomed_users)
        if globalvar.makeWelcomeLog and welcomed_count > 0:
            self.show_status()
            if welcomed_count == 1:
                pywikibot.output('Putting the log of the latest user...')
            else:
                pywikibot.output(
                    'Putting the log of the latest {} users...'
                    .format(welcomed_count))
            self.makelogpage()

        if hasattr(self, '_BAQueue'):
            self.show_status()
            pywikibot.output('Putting bad name to report page...')
            self.report_bad_account()

    @staticmethod
    def show_status(message=Msg.DEFAULT):
        """Output colorized status."""
        msg, color = message.value
        pywikibot.output(color_format('{color}[{msg:5}]{default} ',
                                      msg=msg, color=color),
                         newline=False)

    def teardown(self):
        """Some cleanups after run operation."""
        if self.welcomed_users:
            self.show_status()
            pywikibot.output('Put welcomed users before quit...')
            self.makelogpage()

        # If there is the savedata, the script must save the number_user.
        if globalvar.randomSign and globalvar.saveSignIndex \
           and self.welcomed_users:
            # Filename and Pywikibot path
            # file where is stored the random signature index
            filename = pywikibot.config.datafilepath(
                'welcome-{}-{}.data'.format(self.site.family.name,
                                            self.site.code))
            with open(filename, 'wb') as f:
                pickle.dump(self.welcomed_users, f,
                            protocol=config.pickle_protocol)


def load_word_function(raw) -> List[str]:
    """Load the badword list and the whitelist."""
    page = re.compile(r'(?:\"|\')(.*?)(?:\"|\')(?:, |\))')
    list_loaded = page.findall(raw)
    if not list_loaded:
        pywikibot.output('There was no input on the real-time page.')
    return list_loaded


globalvar = Global()


def _handle_offset(val) -> None:
    """Handle -offset arg."""
    if not val:
        val = pywikibot.input(
            'Which time offset for new users would you like to use? '
            '(yyyymmddhhmmss or yyyymmdd)')
    try:
        globalvar.offset = pywikibot.Timestamp.fromtimestampformat(val)
    except ValueError:
        # upon request, we could check for software version here
        raise ValueError(fill(
            'Mediawiki has changed, -offset:# is not supported anymore, but '
            '-offset:TIMESTAMP is, assuming TIMESTAMP is yyyymmddhhmmss or '
            'yyyymmdd. -timeoffset is now also supported. Please read this '
            'script source header for documentation.'))


def handle_args(args):
    """Process command line arguments.

    If args is an empty list, sys.argv is used.

    :param args: command line arguments
    :type args: str
    """
    mapping = {
        # option: (attribute, value),
        '-break': ('recursive', False),
        '-nlog': ('makeWelcomeLog', False),
        '-ask': ('confirm', True),
        '-filter': ('filtBadName', True),
        '-savedata': ('saveSignIndex', True),
        '-random': ('randomSign', True),
        '-sul': ('welcomeAuto', True),
        '-quiet': ('quiet', True),
    }

    for arg in pywikibot.handle_args(args):
        arg, _, val = arg.partition(':')
        if arg == '-edit':
            globalvar.attachEditCount = int(
                val if val.isdigit() else pywikibot.input(
                    'After how many edits would you like to welcome new users?'
                    ' (0 is allowed)'))
        elif arg == '-timeoffset':
            globalvar.timeoffset = int(
                val if val.isdigit() else pywikibot.input(
                    'Which time offset (in minutes) for new users would you '
                    'like to use?'))
        elif arg == '-time':
            globalvar.timeRecur = int(
                val if val.isdigit() else pywikibot.input(
                    'For how many seconds would you like to bot to sleep '
                    'before checking again?'))
        elif arg == '-offset':
            _handle_offset(val)
        elif arg == '-file':
            globalvar.randomSign = True
            globalvar.signFileName = val or pywikibot.input(
                'Where have you saved your signatures?')
        elif arg == '-sign':
            globalvar.defaultSign = val or pywikibot.input(
                'Which signature to use?')
            globalvar.defaultSign += timeselected
        elif arg == '-limit':
            globalvar.queryLimit = int(
                val if val.isdigit() else pywikibot.input(
                    'How many of the latest new users would you like to '
                    'load?'))
        elif arg == '-numberlog':
            globalvar.dumpToLog = int(
                val if val.isdigit() else pywikibot.input(
                    'After how many welcomed users would you like to update '
                    'the welcome log?'))
        elif arg in mapping:
            setattr(globalvar, *mapping[arg])
        else:
            pywikibot.warning('Unknown option "{}"'.format(arg))


def main(*args: str) -> None:
    """Invoke bot.

    :param args: command line arguments
    """
    handle_args(args)
    if globalvar.offset and globalvar.timeoffset:
        pywikibot.warning(
            'both -offset and -timeoffset were provided, ignoring -offset')
        globalvar.offset = 0

    try:
        bot = WelcomeBot()
    except KeyError as error:
        # site not managed by welcome.py
        pywikibot.bot.suggest_help(exception=error)
    else:
        bot.run()


if __name__ == '__main__':
    main()
