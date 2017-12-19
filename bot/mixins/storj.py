import peewee
from telegram import ChatAction, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler

from bot.api import Barrenero
from bot.models import API, Chat
from bot.state_machine import StatusStateMachine


class StorjMixin:
    storj_status_machine = {}

    def storj(self, bot, update):
        """
        Call for Storj miner status and restarting service.
        """
        chat_id = update.message.chat.id
        bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        keyboard = [
            [
                InlineKeyboardButton("Status", callback_data='[storj_status]'),
                InlineKeyboardButton("Restart", callback_data='[storj_restart]'),
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        bot.send_message(chat_id, 'Select an option:', reply_markup=reply_markup)

    def storj_restart_choice(self, bot, update):
        """
        Call for Storj miner status and restarting service.
        """
        query = update.callback_query
        chat_id = query.message.chat_id
        bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        try:
            chat = Chat.get(id=chat_id)
        except peewee.DoesNotExist:
            chat = False

        if chat:
            buttons = [InlineKeyboardButton(api.name, callback_data=f'[storj_restart][{api.id}]')
                       for api in chat.apis if api.superuser]
            keyboard = [buttons[i:max(len(buttons), i + 4)] for i in range(0, len(buttons), 4)]
            reply_markup = InlineKeyboardMarkup(keyboard)
        else:
            reply_markup = None

        if reply_markup:
            bot.edit_message_text(text='Select miner to restart:', reply_markup=reply_markup, chat_id=chat_id,
                                  message_id=query.message.message_id)
        else:
            bot.edit_message_text(text='No options available', chat_id=chat_id, message_id=query.message.message_id)

    def storj_restart(self, bot, update, groups):
        """
        Restart storj systemd service.
        """
        query = update.callback_query
        api_id = groups[0]
        chat_id = query.message.chat_id

        bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        try:
            api = API.get(id=api_id)

            Barrenero.restart(api.url, api.token, 'Storj')
        except peewee.DoesNotExist:
            self.logger.error('Chat unregistered')
            response_text = 'Configure me first'
            bot.edit_message_text(text=response_text, parse_mode=ParseMode.MARKDOWN, chat_id=chat_id,
                                  message_id=query.message.message_id)
        else:
            response_text = f'Restarting service `{api.name}`.'
            bot.edit_message_text(text=response_text, parse_mode=ParseMode.MARKDOWN, chat_id=chat_id,
                                  message_id=query.message.message_id)

    def storj_status(self, bot, update):
        """
        Check Ether miner status.
        """
        query = update.callback_query
        chat_id = query.message.chat_id

        bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        try:
            chat = Chat.get(id=chat_id)
            data = {api.name: Barrenero.storj(api.url, api.token) for api in chat.apis}
        except peewee.DoesNotExist:
            self.logger.error('Chat unregistered')
            response_text = 'Configure me first'
        else:
            response_text = ''
            for api, result in data.items():
                if result:
                    node_texts = []
                    for node in result:
                        shared = node['shared'] if node['shared'] is not None else 'Unknown'
                        shared_percent = f'{node["shared_percent"]}%' if node[
                                                                             'shared_percent'] is not None else 'Unknown'
                        data_received = node['data_received'] if node['data_received'] is not None else 'Unknown'
                        delta = f'{node["delta"]:d} ms' if node['delta'] is not None else 'Unknown'
                        node_texts.append(
                            f'*API {api} - Storj node #{node["id"]}*\n'
                            f' - Status: `{node["status"]}`\n'
                            f' - Uptime: `{node["uptime"]} ({node["restarts"]} restarts)`\n'
                            f' - Shared: `{shared} ({shared_percent})`\n'
                            f' - Data received: `{data_received}`\n'
                            f' - Peers/Allocs: `{node["peers"]:d}` / `{node["allocs"]:d}`\n'
                            f' - Delta: `{delta}`\n'
                            f' - Path: `{node["config_path"]}`')
                    response_text = '\n\n'.join(node_texts)
                else:
                    response_text = f'*API {api}*\nCannot retrieve Storj miner status'
        finally:
            bot.edit_message_text(text=response_text, parse_mode=ParseMode.MARKDOWN, chat_id=chat_id,
                                  message_id=query.message.message_id)

    def storj_job_status(self, bot, job):
        """
        Check miner status
        """
        # Create new state machines
        new_machines = {a: StatusStateMachine('Storj', a.name)
                        for a in API.select().where(API.superuser == True).join(Chat)
                        if a not in self.storj_status_machine}
        self.storj_status_machine.update(new_machines)

        for api, status in self.storj_status_machine.items():
            data = Barrenero.storj(api.url, api.token)

            node_status = {d['status'] for d in data}
            if node_status == {'running'}:
                status.start(bot=bot, chat=api.chat.id)
            else:
                status.stop(bot=bot, chat=api.chat.id)

    def add_storj_command(self):
        self.dispatcher.add_handler(CommandHandler('storj', self.storj))
        self.dispatcher.add_handler(CallbackQueryHandler(self.storj_restart, pass_groups=True,
                                                         pattern=r'\[storj_restart\]\[(\d+)\]'))
        self.dispatcher.add_handler(CallbackQueryHandler(self.storj_restart_choice, pattern=r'\[storj_restart\]'))
        self.dispatcher.add_handler(CallbackQueryHandler(self.storj_status, pattern=r'\[storj_status\]'))

    def add_storj_jobs(self):
        self.updater.job_queue.run_repeating(self.storj_job_status, 300.0)
