#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# check_recipient_access.py
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

"""
Classes for resolving postfix recipient access
"""

import logging

from twisted.protocols import postfix

from leap.mx.alias_resolver import AliasResolverFactory

logger = logging.getLogger(__name__)


class CheckRecipientAccess(postfix.PostfixTCPMapServer):
    def _cbGot(self, value):
        if value is None:
            self.sendCode(500)
        else:
            self.sendCode(200)


class CheckRecipientAccessFactory(AliasResolverFactory):
    protocol = CheckRecipientAccess
