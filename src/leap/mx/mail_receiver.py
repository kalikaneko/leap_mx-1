#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# mail_receiver.py
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

import os
import uuid as pyuuid
import logging
import argparse
import ConfigParser

import json

from email import message_from_string
from functools import partial

from twisted.internet import inotify, reactor
from twisted.python import filepath

from leap.mx import couchdbhelper

from leap.soledad import LeapDocument
from leap.soledad.backends.leap_backend import EncryptionSchemes
from leap.soledad.backends.couch import CouchDatabase
from leap.common.keymanager import openpgp

logger = logging.getLogger(__name__)


def _get_pubkey(uuid, cdb):
    logger.debug("Fetching pubkey for %s" % (uuid,))
    return uuid, cdb.getPubKey(uuid)


def _encrypt_message(uuid_pubkey, address_message):
    uuid, pubkey = uuid_pubkey
    address, message = address_message
    logger.debug("Encrypting message to %s's pubkey" % (uuid,))
    logger.debug("Pubkey: %s" % (pubkey,))

    doc = LeapDocument(encryption_scheme=EncryptionSchemes.PUBKEY,
                       doc_id=str(pyuuid.uuid4()))

    data = {'incoming': True, 'content': message}

    if pubkey is None or len(pubkey) == 0:
        doc.content = {
            "_unencrypted_json": json.dumps(data)
        }
        return uuid, doc

    def _ascii_to_openpgp_cb(gpg):
        key = gpg.list_keys().pop()
        return openpgp._build_key_from_gpg(address, key, pubkey)

    openpgp_key = openpgp._safe_call(_ascii_to_openpgp_cb, pubkey)

    doc.content = {
        "_encrypted_json": openpgp.encrypt_asym(json.dumps(data), openpgp_key)
    }

    return uuid, doc


def _export_message(uuid_doc, couch_url):
    uuid, doc = uuid_doc
    logger.debug("Exporting message for %s" % (uuid,))

    if uuid is None:
        uuid = 0

    db = CouchDatabase(couch_url, "user-%s" % (uuid,))
    db.put_doc(doc)

    logger.debug("Done exporting")

    return True


def _conditional_remove(do_remove, filepath):
    if do_remove:
        # remove the original mail
        try:
            logger.debug("Removing %s" % (filepath.path,))
            filepath.remove()
            logger.debug("Done removing")
        except Exception as e:
            # TODO: better handle exceptions
            logger.exception("%s" % (e,))


def _process_incoming_email(users_db, mail_couchdb_url_prefix,
                            self, filepath, mask):
    logger.debug('filepath: %s' % filepath)
    if os.path.split(filepath.dirname())[-1] == "new":
        logger.debug("Processing new mail at %s" % (filepath.path,))
        with filepath.open("r") as f:
            mail_data = f.read()
            mail = message_from_string(mail_data)

            owner = mail["To"]
            if owner is None:  # default to Delivered-To
                owner = mail["Delivered-To"]
            if not owner:
                logger.error(
                    "Malformed mail, neither to nor delivered-to field")
                return
            owner = owner.split("@")[0]
            owner = owner.split("+")[0]
            logger.debug("Mail owner: %s" % (owner,))

            logger.debug("%s received a new mail" % (owner,))
            d = users_db.queryByLoginOrAlias(owner)
            d.addCallback(_get_pubkey, (users_db))
            d.addCallback(_encrypt_message, (owner, mail_data))
            d.addCallback(_export_message, (mail_couchdb_url_prefix))
            d.addCallback(_conditional_remove, (filepath))


def main():
    epilog = "Copyright 2012 The LEAP Encryption Access Project"
    parser = argparse.ArgumentParser(description="""LEAP MX Mail receiver""",
                                     epilog=epilog)
    parser.add_argument('-d', '--debug', action="store_true",
                        help="Launches the LEAP MX mail receiver with "
                        "debug output")
    parser.add_argument('-l', '--logfile', metavar="LOG FILE", nargs='?',
                        action="store", dest="log_file",
                        help="Writes the logs to the specified file")
    parser.add_argument('-c', '--config', metavar="CONFIG FILE", nargs='?',
                        action="store", dest="config",
                        help="Where to look for the configuration file. "
                        "Default: mail_receiver.cfg")

    opts, _ = parser.parse_known_args()

    debug = opts.debug
    config_file = opts.config

    if debug:
        level = logging.DEBUG
    else:
        level = logging.WARNING

    if config_file is None:
        config_file = "leap_mx.cfg"

    logger.setLevel(level)
    console = logging.StreamHandler()
    console.setLevel(level)
    formatter = logging.Formatter(
        '%(asctime)s '
        '- %(name)s - %(levelname)s - %(message)s')
    console.setFormatter(formatter)
    logger.addHandler(console)

    logger.info("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
    logger.info("    LEAP MX Mail receiver")
    logger.info("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")

    logger.info("Reading configuration from %s" % (config_file,))

    config = ConfigParser.ConfigParser()
    config.read(config_file)

    users_user = config.get("couchdb", "users_user")
    users_password = config.get("couchdb", "users_password")

    mail_user = config.get("couchdb", "mail_user")
    mail_password = config.get("couchdb", "mail_password")

    server = config.get("couchdb", "server")
    port = config.get("couchdb", "port")

    wm = inotify.INotify(reactor)
    wm.startReading()

    mask = inotify.IN_CREATE

    users_db = couchdbhelper.ConnectedCouchDB(server,
                                              port=port,
                                              dbName="users",
                                              username=users_user,
                                              password=users_password)

    mail_couch_url_prefix = "http://%s:%s@localhost:%s" % (mail_user,
                                                           mail_password,
                                                           port)

    incoming_partial = partial(
        _process_incoming_email, users_db, mail_couch_url_prefix)
    for section in config.sections():
        if section in ("couchdb"):
            continue
        to_watch = config.get(section, "path")
        recursive = config.getboolean(section, "recursive")
        logger.debug("Watching %s --- Recursive: %s" % (to_watch, recursive))
        wm.watch(
            filepath.FilePath(to_watch),
            mask,
            callbacks=[incoming_partial],
            recursive=recursive)

    reactor.run()

if __name__ == "__main__":
    main()
