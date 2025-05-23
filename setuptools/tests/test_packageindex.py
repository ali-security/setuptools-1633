import sys
import os
import distutils.errors
import platform
import urllib.request
import urllib.error
import http.client

import mock
import pytest

import setuptools.package_index
from .textwrap import DALS


class TestPackageIndex:
    def test_regex(self):
        hash_url = 'http://other_url?:action=show_md5&amp;'
        hash_url += 'digest=0123456789abcdef0123456789abcdef'
        doc = """
            <a href="http://some_url">Name</a>
            (<a title="MD5 hash"
            href="{hash_url}">md5</a>)
        """.lstrip().format(**locals())
        assert setuptools.package_index.PYPI_MD5.match(doc)

    def test_bad_url_bad_port(self):
        index = setuptools.package_index.PackageIndex()
        url = 'http://127.0.0.1:0/nonesuch/test_package_index'
        try:
            v = index.open_url(url)
        except Exception as v:
            assert url in str(v)
        else:
            assert isinstance(v, urllib.error.HTTPError)

    def test_bad_url_typo(self):
        # issue 16
        # easy_install inquant.contentmirror.plone breaks because of a typo
        # in its home URL
        index = setuptools.package_index.PackageIndex(
            hosts=('www.example.com',)
        )

        url = (
            'url:%20https://svn.plone.org/svn'
            '/collective/inquant.contentmirror.plone/trunk'
        )
        try:
            v = index.open_url(url)
        except Exception as v:
            assert url in str(v)
        else:
            assert isinstance(v, urllib.error.HTTPError)

    def test_bad_url_bad_status_line(self):
        index = setuptools.package_index.PackageIndex(
            hosts=('www.example.com',)
        )

        def _urlopen(*args):
            raise http.client.BadStatusLine('line')

        index.opener = _urlopen
        url = 'http://example.com'
        try:
            index.open_url(url)
        except Exception as exc:
            assert 'line' in str(exc)
        else:
            raise AssertionError('Should have raise here!')

    def test_bad_url_double_scheme(self):
        """
        A bad URL with a double scheme should raise a DistutilsError.
        """
        index = setuptools.package_index.PackageIndex(
            hosts=('www.example.com',)
        )

        # issue 20
        url = 'http://http://svn.pythonpaste.org/Paste/wphp/trunk'
        try:
            index.open_url(url)
        except distutils.errors.DistutilsError as error:
            msg = str(error)
            assert (
                'nonnumeric port' in msg
                or 'getaddrinfo failed' in msg
                or 'Name or service not known' in msg
            )
            return
        raise RuntimeError("Did not raise")

    def test_bad_url_screwy_href(self):
        index = setuptools.package_index.PackageIndex(
            hosts=('www.example.com',)
        )

        # issue #160
        if sys.version_info[0] == 2 and sys.version_info[1] == 7:
            # this should not fail
            url = 'http://example.com'
            page = ('<a href="http://www.famfamfam.com]('
                    'http://www.famfamfam.com/">')
            index.process_index(url, page)

    def test_url_ok(self):
        index = setuptools.package_index.PackageIndex(
            hosts=('www.example.com',)
        )
        url = 'file:///tmp/test_package_index'
        assert index.url_ok(url, True)

    def test_parse_bdist_wininst(self):
        parse = setuptools.package_index.parse_bdist_wininst

        actual = parse('reportlab-2.5.win32-py2.4.exe')
        expected = 'reportlab-2.5', '2.4', 'win32'
        assert actual == expected

        actual = parse('reportlab-2.5.win32.exe')
        expected = 'reportlab-2.5', None, 'win32'
        assert actual == expected

        actual = parse('reportlab-2.5.win-amd64-py2.7.exe')
        expected = 'reportlab-2.5', '2.7', 'win-amd64'
        assert actual == expected

        actual = parse('reportlab-2.5.win-amd64.exe')
        expected = 'reportlab-2.5', None, 'win-amd64'
        assert actual == expected

    def test__vcs_split_rev_from_url(self):
        """
        Test the basic usage of _vcs_split_rev_from_url
        """
        vsrfu = setuptools.package_index.PackageIndex._vcs_split_rev_from_url
        url, rev = vsrfu('https://example.com/bar@2995')
        assert url == 'https://example.com/bar'
        assert rev == '2995'

    def test_local_index(self, tmpdir):
        """
        local_open should be able to read an index from the file system.
        """
        index_file = tmpdir / 'index.html'
        with index_file.open('w') as f:
            f.write('<div>content</div>')
        url = 'file:' + urllib.request.pathname2url(str(tmpdir)) + '/'
        res = setuptools.package_index.local_open(url)
        assert 'content' in res.read()

    def test_egg_fragment(self):
        """
        EGG fragments must comply to PEP 440
        """
        epoch = [
            '',
            '1!',
        ]
        releases = [
            '0',
            '0.0',
            '0.0.0',
        ]
        pre = [
            'a0',
            'b0',
            'rc0',
        ]
        post = [
            '.post0'
        ]
        dev = [
            '.dev0',
        ]
        local = [
            ('', ''),
            ('+ubuntu.0', '+ubuntu.0'),
            ('+ubuntu-0', '+ubuntu.0'),
            ('+ubuntu_0', '+ubuntu.0'),
        ]
        versions = [
            [''.join([e, r, p, loc]) for loc in locs]
            for e in epoch
            for r in releases
            for p in sum([pre, post, dev], [''])
            for locs in local]
        for v, vc in versions:
            dists = list(setuptools.package_index.distros_for_url(
                'http://example.com/example.zip#egg=example-' + v))
            assert dists[0].version == ''
            assert dists[1].version == vc

    def test_download_git_with_rev(self, tmpdir):
        url = 'git+https://github.example/group/project@master#egg=foo'
        index = setuptools.package_index.PackageIndex()

        with mock.patch("os.system") as os_system_mock:
            result = index.download(url, str(tmpdir))

        os_system_mock.assert_called()

        expected_dir = str(tmpdir / 'project@master')
        expected = (
            'git clone --quiet '
            'https://github.example/group/project {expected_dir}'
        ).format(**locals())
        first_call_args = os_system_mock.call_args_list[0][0]
        assert first_call_args == (expected,)

        tmpl = 'git -C {expected_dir} checkout --quiet master'
        expected = tmpl.format(**locals())
        assert os_system_mock.call_args_list[1][0] == (expected,)
        assert result == expected_dir

    def test_download_git_no_rev(self, tmpdir):
        url = 'git+https://github.example/group/project#egg=foo'
        index = setuptools.package_index.PackageIndex()

        with mock.patch("os.system") as os_system_mock:
            result = index.download(url, str(tmpdir))

        os_system_mock.assert_called()

        expected_dir = str(tmpdir / 'project')
        expected = (
            'git clone --quiet '
            'https://github.example/group/project {expected_dir}'
        ).format(**locals())
        os_system_mock.assert_called_once_with(expected)

    def test_download_svn(self, tmpdir):
        url = 'svn+https://svn.example/project#egg=foo'
        index = setuptools.package_index.PackageIndex()

        with pytest.warns(UserWarning):
            with mock.patch("os.system") as os_system_mock:
                result = index.download(url, str(tmpdir))

        os_system_mock.assert_called()

        expected_dir = str(tmpdir / 'project')
        expected = (
            'svn checkout -q '
            'svn+https://svn.example/project {expected_dir}'
        ).format(**locals())
        os_system_mock.assert_called_once_with(expected)


class TestContentCheckers:
    def test_md5(self):
        checker = setuptools.package_index.HashChecker.from_url(
            'http://foo/bar#md5=f12895fdffbd45007040d2e44df98478')
        checker.feed('You should probably not be using MD5'.encode('ascii'))
        assert checker.hash.hexdigest() == 'f12895fdffbd45007040d2e44df98478'
        assert checker.is_valid()

    def test_other_fragment(self):
        "Content checks should succeed silently if no hash is present"
        checker = setuptools.package_index.HashChecker.from_url(
            'http://foo/bar#something%20completely%20different')
        checker.feed('anything'.encode('ascii'))
        assert checker.is_valid()

    def test_blank_md5(self):
        "Content checks should succeed if a hash is empty"
        checker = setuptools.package_index.HashChecker.from_url(
            'http://foo/bar#md5=')
        checker.feed('anything'.encode('ascii'))
        assert checker.is_valid()

    def test_get_hash_name_md5(self):
        checker = setuptools.package_index.HashChecker.from_url(
            'http://foo/bar#md5=f12895fdffbd45007040d2e44df98478')
        assert checker.hash_name == 'md5'

    def test_report(self):
        checker = setuptools.package_index.HashChecker.from_url(
            'http://foo/bar#md5=f12895fdffbd45007040d2e44df98478')
        rep = checker.report(lambda x: x, 'My message about %s')
        assert rep == 'My message about md5'


@pytest.fixture
def temp_home(tmpdir, monkeypatch):
    key = (
        'USERPROFILE'
        if platform.system() == 'Windows' and sys.version_info > (3, 8) else
        'HOME'
    )

    monkeypatch.setitem(os.environ, key, str(tmpdir))
    return tmpdir


class TestPyPIConfig:
    def test_percent_in_password(self, temp_home):
        pypirc = temp_home / '.pypirc'
        pypirc.write(DALS("""
            [pypi]
            repository=https://pypi.org
            username=jaraco
            password=pity%
        """))
        cfg = setuptools.package_index.PyPIConfig()
        cred = cfg.creds_by_repository['https://pypi.org']
        assert cred.username == 'jaraco'
        assert cred.password == 'pity%'


@pytest.mark.timeout(1)
def test_REL_DoS():
    """
    """
