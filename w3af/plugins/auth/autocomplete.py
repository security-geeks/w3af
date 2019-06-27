"""
autocomplete.py

Copyright 2019 Andres Riancho

This file is part of w3af, http://w3af.org/ .

w3af is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation version 2 of the License.

w3af is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with w3af; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

"""
import w3af.core.controllers.output_manager as om
import w3af.core.data.parsers.parser_cache as parser_cache

from w3af.core.data.options.opt_factory import opt_factory
from w3af.core.data.options.option_list import OptionList
from w3af.core.data.dc.factory import dc_from_form_params
from w3af.core.data.options.option_types import URL as URL_OPT, STRING
from w3af.core.data.parsers.doc.url import URL
from w3af.core.controllers.plugins.auth_plugin import AuthPlugin
from w3af.core.controllers.exceptions import BaseFrameworkException
from w3af.core.data.request.fuzzable_request import FuzzableRequest


class autocomplete(AuthPlugin):
    """
    Fill and submit login forms
    """

    def __init__(self):
        AuthPlugin.__init__(self)

        # User configured settings
        self.username = ''
        self.password = ''
        self.login_form_url = URL('http://host.tld/login')
        self.check_url = URL('http://host.tld/check')
        self.check_string = ''

        # Internal attributes
        self._attempt_login = True

    def login(self):
        """
        Login to the application:
            * HTTP GET `login_form_url`
            * Parse the HTML in `login_form_url` and find the login form
            * Fill the form with the user-configured credentials
            * Submit the form
        """
        #
        # In some cases the authentication plugin is incorrectly configured and
        # we don't want to keep trying over and over to login when we know it
        # will fail
        #
        if not self._attempt_login:
            return

        msg = 'Logging into the application with user: %s' % self.username
        om.out.debug(msg)

        #
        # First we send the request to `login_form_url` and then we extract
        # the HTML form. If there are any problems in this step, just skip
        # the next calls to login()
        #
        form = self._get_login_form()

        if not form:
            self._attempt_login = False
            return False

        #
        # Complete the parameters and send the form to the server
        #
        form_submitted = self._submit_form(form)

        if not form_submitted:
            return False

        if not self.has_active_session():
            msg = "Can't login into the web application as %s"
            om.out.error(msg % self.username)
            return False

        om.out.debug('Login success for %s' % self.username)
        return True

    def _submit_form(self, form_params):
        """
        Complete the username and password in the form fields and submit it
        to the server.

        :param form_params: The form parameters as returned by the HTML parser
        :return: True if form was submitted to the server
        """
        #
        # Create a form instance, using the proper encoding (multipart
        # or url). The form_params instance only has the parameters and can
        # not be sent to the wire.
        #
        form = dc_from_form_params(form_params)

        form.set_login_username(self.username)
        form.set_login_password(self.password)

        #
        # Transform to a fuzzable request and send to the wire
        #
        fuzzable_request = FuzzableRequest.from_form(form)

        try:
            self._uri_opener.send_mutant(fuzzable_request,
                                         grep=False,
                                         cache=False,
                                         follow_redirects=True)
        except Exception, e:
            msg = 'Failed to submit the login form: %s'
            om.out.debug(msg % e)
            return False

        return True

    def _get_login_form(self):
        """
        Parse the HTML returned from `login_form_url` and find the HTML form
        that can be used to login to the application.

        :return: A Form instance
        """
        #
        # Send the HTTP GET request to retrieve the HTML
        #
        try:
            http_response = self._uri_opener.GET(self.login_form_url,
                                                 grep=False,
                                                 cache=False,
                                                 follow_redirects=True)
        except Exception as e:
            msg = 'Failed to HTTP GET the login_form_url: %s'
            om.out.debug(msg % e)
            return

        #
        # Extract the form from the HTML document
        #
        try:
            document_parser = parser_cache.dpc.get_document_parser_for(http_response)
        except BaseFrameworkException as e:
            msg = 'Failed to find a parser for the login_form_url: %s'
            om.out.debug(msg % e)
            return

        login_form = None

        for form_params in document_parser.get_forms():
            #
            # Find a form that:
            #
            #   * Is a login form
            #   * The action points to the target domain
            #   * This is the only login form in the page
            #
            if not form_params.is_login_form():
                continue

            if form_params.get_action().get_domain() != self.login_form_url.get_domain():
                continue

            if login_form is not None:
                #
                # There are two or more login forms in this page
                #
                om.out.debug('There are two or more login forms in the login_form_url.'
                             ' This is not supported by the autocomplete authentication'
                             ' plugin, using the first identified form and crossing'
                             ' fingers.')
                continue

            login_form = form_params

        if login_form is None:
            msg = ('Failed to find an HTML login form at %s. The authentication'
                   ' plugin is most likely incorrectly configured.')
            args = (self.login_form_url,)
            om.out.error(msg % args)

        return login_form

    def logout(self):
        """
        User logout
        """
        return None

    def has_active_session(self):
        """
        Check user session.
        """
        try:
            http_response = self._uri_opener.GET(self.check_url,
                                                 grep=False,
                                                 cache=False,
                                                 follow_redirects=True)
        except Exception, e:
            msg = 'Failed to check if current authentication session is active: %s'
            om.out.debug(msg % e)
            return False

        else:
            body = http_response.get_body()
            logged_in = self.check_string in body

            msg_yes = 'User "%s" is currently logged into the application'
            msg_no = 'User "%s" is NOT logged into the application'
            msg = msg_yes if logged_in else msg_no
            om.out.debug(msg % self.username)

            return logged_in

    def get_options(self):
        """
        :return: A list of option objects for this plugin.
        """
        options = [
            ('username', self.username, STRING,
             'Username for the authentication process'),

            ('password', self.password, STRING,
             'Password for the authentication process'),

            ('login_form_url', self.login_form_url, URL_OPT,
             'The URL where the login form appears'),

            ('check_url', self.check_url, URL_OPT,
             'URL used to verify if the session is active. The plugin sends'
             ' an HTTP GET request to this URL and asserts if `check_string`'
             ' is present.'),

            ('check_string', self.check_string, STRING,
             'String to search in the `check_url` page to determine if the'
             ' session is active.'),
        ]

        ol = OptionList()

        for o in options:
            ol.add(opt_factory(o[0], o[1], o[3], o[2], help=o[3]))

        return ol

    def set_options(self, options_list):
        """
        This method sets all the options that are configured using
        the user interface generated by the framework using
        the result of get_options().

        :param options_list: A dict with the options for the plugin.
        :return: No value is returned.
        """
        self.username = options_list['username'].get_value()
        self.password = options_list['password'].get_value()
        self.check_string = options_list['check_string'].get_value()
        self.login_form_url = options_list['login_form_url'].get_value()
        self.check_url = options_list['check_url'].get_value()

        missing_options = []

        for o in options_list:
            if not o.get_value():
                missing_options.append(o.get_name())

        if missing_options:
            msg = ("All parameters are required and can't be empty."
                   " The missing parameters are %s")
            raise BaseFrameworkException(msg % ', '.join(missing_options))

    def get_long_desc(self):
        """
        :return: A DETAILED description of the plugin functions and features.
        """
        return """
        This authentication plugin can login to Web applications which use
        common authentication schemes, including those which use CSRF tokens.

        The plugin performs an HTTP GET request on `login_form_url` to obtain
        the HTML form parameters and values, fills the `username` and
        `password` fields and then submits the form (usually with HTTP POST)
        to authenticate the user. 

        The following configurable parameters exist:
            - username
            - password
            - login_form_url
            - check_url
            - check_string
        """
