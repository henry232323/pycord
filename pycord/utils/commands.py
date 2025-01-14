

import inspect
import shlex
from .converter import Converter


class Command:
    def __init__(self, **kwargs):
        self.callback = kwargs.get('callback')
        self.name = kwargs.get('name')
        self.aliases = [self.name] + kwargs.get('aliases', [])
        self.help_doc = inspect.getdoc(self.callback)
        self.check = inspect.signature(self.callback).return_annotation
        self.signature = inspect.signature(self.callback).parameters.items()


def cmd(name=None, *, callback=None, aliases=[]):
    if isinstance(aliases, str):
        aliases = [aliases]
    if inspect.iscoroutinefunction(callback):
        name = name or callback.__name__
        cmd = Command(name=name, callback=callback, aliases=aliases)
        return cmd
    else:
        def wrapper(coro):
            if not inspect.iscoroutinefunction(coro):
                raise RuntimeWarning('Callback is not a coroutine!')
            cmd = Command(name=name or coro.__name__, callback=coro, aliases=aliases)
            return cmd

        return wrapper


class Context:
    def __init__(self, client, message):
        self.client = client
        self.message = message

    @property
    def session(self):
        return self.client.session

    @property
    def author(self):
        return self.message.author

    @property
    def guild(self):
        return self.message.guild

    @property
    def channel(self):
        return self.message.channel

    @property
    def content(self):
        return self.message.content

    @property
    def command(self):
        if self.prefix is None:
            return None
        for command in self.client.commands:
            for alias in command.aliases:
                if self.content.startswith(self.prefix + alias):
                    return command
        return None

    @property
    def callback(self):
        return self.command.callback

    @property
    def alias(self):
        for command in self.client.commands:
            for alias in command.aliases:
                if self.content.startswith(self.prefix + alias):
                    return alias
        return None

    @property
    def prefix(self):
        for prefix in self.client.prefixes:
            if self.content.startswith(prefix):
                return prefix

    @property
    def command_content(self):
        cut = len(self.prefix + self.alias)
        return self.content[cut:]

    async def invoke(self):
        if self.command is None:
            return
        if not self.client.is_bot:
            if self.message.author.id != self.client.user.id:
                return
        args, kwargs = await self.get_arguments()
        callback = self.command.callback
        check = self.command.check
        should_call = True
        if check is not inspect._empty:
            if inspect.iscoroutinefunction(check):
                should_call = await check(self)
            else:
                should_call = check(self)

        if not should_call:
            return
        try:
            await callback(self, *args, **kwargs)
        except Exception as e:
            await self.client.emit('command_error', e)

    async def get_arguments(self):
        signature = self.command.signature
        try:
            splitted = shlex.split(self.command_content, posix=False)
        except:
            splitted = self.command_content.split()

        arguments = []
        kwargs = {}

        for index, (name, param) in enumerate(signature):
            if index == 0:
                continue
            if param.kind is param.POSITIONAL_OR_KEYWORD:
                arg = await self.convert(param, splitted.pop(0).strip('\'"'))
                arguments.append(arg)
            if param.kind is param.VAR_KEYWORD:
                for arg in splitted:
                    arg = await self.convert(param, arg)
                    arguments.append(arg)
            if param.kind is param.KEYWORD_ONLY:
                arg = await self.convert(param, ' '.join(splitted))
                kwargs[name] = arg

        for key in kwargs.copy():
            if not kwargs[key]:
                kwargs.pop(key)

        return arguments, kwargs

    async def convert(self, param, value):
        converter = self.get_converter(param)
        if inspect.isclass(converter) and issubclass(converter, Converter):
            obj = converter(self, value)
            converter = obj.convert
        else:
            return converter(value)
        if inspect.iscoroutinefunction(converter):
            return await converter(self, value)
        else:
            return converter(self, value)

    def get_converter(self, param):
        if param.annotation is param.empty:
            return str
        if callable(param.annotation):
            return param.annotation
        else:
            raise ValueError('Parameter annotation must be callable')

    def reply(self, content, **kwargs):
        return self.message.reply(content, **kwargs)


class CommandCollection:
    def __init__(self, client):
        self.client = client
        self.commands = {}

    def __iter__(self):
        for cmd in self.commands.values():
            yield cmd

    def _is_already_registered(self, cmd):
        for command in self.commands.values():
            for alias in cmd.aliases:
                if alias in command.aliases:
                    return True

    def add(self, cmd):
        if not isinstance(cmd, Command):
            raise ValueError('cmd must be a subclass of Command')
        if self._is_already_registered(cmd):
            raise ValueError('A name or alias is already registered')
        self.commands[cmd.name] = cmd

    def get(self, alias, prefix='', fallback=None):
        try:
            return self.commands[alias]
        except KeyError:
            pass
        for command in self.commands:
            if alias in command.aliases:
                return command
        return fallback
