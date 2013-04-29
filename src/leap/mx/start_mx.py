#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# start_mx.py
# Copyright (C) 2013 LEAP
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import ConfigParser
import logging

from functools import partial

from leap.mx import couchdbhelper, mail_receiver
from leap.mx.alias_resolver import AliasResolverFactory
from leap.mx.check_recipient_access import CheckRecipientAccessFactory

try:
    from twisted.internet import reactor, inotify
    from twisted.internet.endpoints import TCP4ServerEndpoint
    from twisted.python import filepath
except ImportError, ie:
    print "This software requires Twisted>=12.0.2, please see the README for"
    print "help on using virtualenv and pip to obtain requirements."


def main():
    epilog = "Copyright 2012 The LEAP Encryption Access Project"
    parser = argparse.ArgumentParser(description="""LEAP MX""",
                                     epilog=epilog)
    parser.add_argument(
        '-d', '--debug', action="store_true",
        help="Launches the LEAP MX mail receiver with debug output")
    parser.add_argument(
        '-l', '--logfile', metavar="LOG FILE", nargs='?',
        action="store", dest="log_file",
        help="Writes the logs to the specified file")
    parser.add_argument(
        '-c', '--config', metavar="CONFIG FILE", nargs='?',
        action="store", dest="config",
        help="Where to look for the configuration file. "
        "Default: mail_receiver.cfg")

    opts, _ = parser.parse_known_args()

    logger = logging.getLogger(name='leap')

    debug = opts.debug
    config_file = opts.config
    logfile = opts.log_file

    if debug:
        level = logging.DEBUG
    else:
        level = logging.WARNING

    if config_file is None:
        config_file = "mx.conf"

    logger.setLevel(level)
    console = logging.StreamHandler()
    console.setLevel(level)
    formatter = logging.Formatter(
        '%(asctime)s '
        '- %(name)s - %(levelname)s - %(message)s')
    console.setFormatter(formatter)
    logger.addHandler(console)

    if logfile is not None:
        logger.debug('Setting logfile to %s ', logfile)
        fileh = logging.FileHandler(logfile)
        fileh.setLevel(logging.DEBUG)
        fileh.setFormatter(formatter)
        logger.addHandler(fileh)

    logger.info("~~~~~~~~~~~~~~~~~~~")
    logger.info("    LEAP MX")
    logger.info("~~~~~~~~~~~~~~~~~~~")

    logger.info("Reading configuration from %s" % (config_file,))

    config = ConfigParser.ConfigParser()
    config.read(config_file)

    user = config.get("couchdb", "user")
    password = config.get("couchdb", "password")

    server = config.get("couchdb", "server")
    port = config.get("couchdb", "port")

    cdb = couchdbhelper.ConnectedCouchDB(server,
                                         port=port,
                                         dbName="users",
                                         username=user,
                                         password=password)

    # Mail receiver
    wm = inotify.INotify(reactor)
    wm.startReading()

    mask = inotify.IN_CREATE

    mail_couch_url_prefix = "http://%s:%s@%s:%s" % (user,
                                                    password,
                                                    server,
                                                    port)

    incoming_partial = partial(
        mail_receiver._process_incoming_email, cdb, mail_couch_url_prefix)

    for section in config.sections():
        if section in ("couchdb"):
            continue
        to_watch = config.get(section, "path")
        recursive = config.getboolean(section, "recursive")
        logger.debug("Watching %s --- Recursive: %s" % (to_watch, recursive))
        wm.watch(filepath.FilePath(to_watch),
                 mask, callbacks=[incoming_partial], recursive=recursive)

    # Alias map
    alias_endpoint = TCP4ServerEndpoint(reactor, 4242)
    alias_endpoint.listen(AliasResolverFactory(couchdb=cdb))

    # Check recipient access
    check_recipient = TCP4ServerEndpoint(reactor, 2244)
    check_recipient.listen(CheckRecipientAccessFactory(couchdb=cdb))

    reactor.run()

if __name__ == "__main__":
    main()
