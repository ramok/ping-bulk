"""Kiosk mode refuses the SSH options that would hand the console a shell.

``:set ssh-options`` is typeable at the kiosk console and the blocklist is its
only guard, so every spelling ssh itself accepts has to be recognised here.
The three that were not, each verified against OpenSSH 10.0p2 with ``-G``:

* ``-o 'ProxyCommand /bin/sh'`` — ssh_config(5) separates a keyword from its
  argument with whitespace as readily as with ``=``;
* ``-o ' ProxyCommand=/bin/sh'`` — ssh ignores whitespace around either;
* ``KnownHostsCommand`` and ``PKCS11Provider``, which were simply not listed.
  ``KnownHostsCommand`` was confirmed to actually run its argument.
"""

import pytest

# Every option that must never reach ssh, in the casing a user would type.
BLOCKED = [
    'ProxyCommand', 'LocalCommand', 'PermitLocalCommand', 'ProxyUseFdpass',
    'ControlMaster', 'RemoteForward', 'LocalForward', 'DynamicForward',
    'KnownHostsCommand', 'PKCS11Provider',
]


class TestBlocklistShape:
    def test_every_entry_is_lowercase(self, pb):
        """The lookup lowercases, so a mixed-case entry can never match."""
        wrong = sorted(k for k in pb._KIOSK_SSH_BLOCKLIST if k != k.lower())
        assert wrong == [], (
            "these entries can never match a .lower()ed key: %s" % wrong
        )

    def test_the_dangerous_names_are_all_listed(self, pb):
        missing = [n for n in BLOCKED if n.lower() not in pb._KIOSK_SSH_BLOCKLIST]
        assert missing == []


class TestOptionKey:
    @pytest.mark.parametrize('text', [
        'ProxyCommand=/bin/sh',
        'ProxyCommand /bin/sh',
        ' ProxyCommand=/bin/sh',
        'ProxyCommand = /bin/sh',
        '\tProxyCommand\t/bin/sh',
        'ProxyCommand=',
        'ProxyCommand',
    ])
    def test_the_keyword_is_found_however_it_is_separated(self, pb, text):
        assert pb._kiosk_ssh_option_key(text) == 'ProxyCommand'

    def test_the_spelling_is_preserved_for_the_message(self, pb):
        assert pb._kiosk_ssh_option_key('pRoXyCoMmAnD=x') == 'pRoXyCoMmAnD'


class TestValidation:
    @pytest.mark.parametrize('key', BLOCKED)
    @pytest.mark.parametrize('args', [
        ['-o', '%s=x'], ['-o%s=x'],
        ['-o', '%s x'], ['-o%s x'],
        ['-o', ' %s = x'],
    ], ids=['sep-eq', 'inline-eq', 'sep-space', 'inline-space', 'sep-padded'])
    def test_every_blocked_option_in_every_spelling(self, pb, key, args):
        msg = pb._kiosk_validate_ssh_args([a % key if '%s' in a else a
                                           for a in args])
        assert msg is not None
        assert key in msg

    @pytest.mark.parametrize('spelling', [
        'ProxyUseFdpass', 'proxyusefdpass', 'PROXYUSEFDPASS', 'proxyUseFdPass',
    ])
    def test_case_does_not_matter(self, pb, spelling):
        assert pb._kiosk_validate_ssh_args(['-o', '%s=yes' % spelling]) is not None

    def test_it_finds_a_blocked_option_after_allowed_ones(self, pb):
        assert pb._kiosk_validate_ssh_args(
            ['-o', 'BatchMode=yes', '-p', '2222',
             '-o', 'ProxyCommand /bin/sh', 'host']) is not None

    @pytest.mark.parametrize('args', [
        ['-o', 'ConnectTimeout=5', '-o', 'BatchMode=yes'],
        ['-o', 'ConnectTimeout 5'],
        ['-o', 'ControlPath=none'],
        ['-p', '2222', 'host'],
        ['-o'],
        [],
    ])
    def test_allowed_arguments_pass(self, pb, args):
        assert pb._kiosk_validate_ssh_args(args) is None

    def test_a_value_that_mentions_a_blocked_name_is_not_a_false_positive(self, pb):
        """The keyword is the first word; what follows it is a value."""
        assert pb._kiosk_validate_ssh_args(
            ['-o', 'ConnectTimeout=5', '-o', 'IdentityFile=/k/proxycommand']) is None
