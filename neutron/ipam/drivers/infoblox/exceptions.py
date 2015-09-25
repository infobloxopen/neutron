# Copyright 2014 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from neutron.common import exceptions


class InfobloxException(exceptions.NeutronException):
    """Generic Infoblox Exception."""
    def __init__(self, response, **kwargs):
        self.response = response
        super(InfobloxException, self).__init__(**kwargs)


class InfobloxIsMisconfigured(exceptions.NeutronException):
    message = _("Infoblox IPAM is misconfigured: infoblox_wapi, "
                "infoblox_username and infoblox_password must be defined.")


class InfobloxSearchError(InfobloxException):
    message = _("Cannot search '%(objtype)s' object(s): "
                "%(content)s [code %(code)s]")


class InfobloxCannotCreateObject(InfobloxException):
    message = _("Cannot create '%(objtype)s' object(s): "
                "%(content)s [code %(code)s]")


class InfobloxCannotDeleteObject(InfobloxException):
    message = _("Cannot delete object with ref %(ref)s: "
                "%(content)s [code %(code)s]")


class InfobloxCannotUpdateObject(InfobloxException):
    message = _("Cannot update object with ref %(ref)s: "
                "%(content)s [code %(code)s]")


class InfobloxFuncException(InfobloxException):
    message = _("Error occured during function's '%(func_name)s' call: "
                "ref %(ref)s: %(content)s [code %(code)s]")


class InfobloxHostRecordIpAddrNotCreated(exceptions.NeutronException):
    message = _("Infoblox host record ipv4addr/ipv6addr has not been "
                "created for IP %(ip)s, mac %(mac)s")



class InfobloxCannotAllocateIpForSubnet(exceptions.NeutronException):
    message = _("Infoblox Network view %(netview)s, Network %(cidr)s "
                "does not have IPs available for allocation.")


class InfobloxCannotAllocateIp(exceptions.NeutronException):
    message = _("Cannot allocate IP %(ip_data)s")


class InfobloxDidNotReturnCreatedIPBack(exceptions.NeutronException):
    message = _("Infoblox did not return created IP back")


class InfobloxNetworkNotAvailable(exceptions.NeutronException):
    message = _("No network view %(net_view_name)s for %(cidr)s")


class InfobloxObjectParsingError(exceptions.NeutronException):
    message = _("Infoblox object cannot be parsed from dict: %(data)s")


class HostRecordNotPresent(InfobloxObjectParsingError):
    message = _("Cannot parse Host Record object from dict because "
                "'ipv4addrs'/'ipv6addrs' is absent.")


class InfobloxInvalidIp(InfobloxObjectParsingError):
    message = _("Bad IP address: %(ip)s")


class NoAttributeInInfobloxObject(exceptions.NeutronException):
    message = _("To find OpenStack %(os_object)s for Infoblox %(ib_object)s, "
                "%(attribute)s must be in extensible attributes.")


class OperationNotAllowed(exceptions.NeutronException):
    message = _("Requested operation is not allowed: %(reason)s")


class InfobloxConnectionError(exceptions.NeutronException):
    message = _("Infoblox HTTP request failed with: %(reason)s")


class InfobloxConfigException(exceptions.NeutronException):
    """Generic Infoblox Config Exception."""
    message = _("Config error: %(msg)s")


class InfobloxInternalPrivateSubnetAlreadyExist(exceptions.Conflict):
    message = _("Network with the same CIDR already exists on NIOS.")


class InfobloxNetworkTypeNotAllowed(InfobloxException):
    message = _("Network with network_type '%(network_type)s' "
                "not allowed by NIOS.")


class InfobloxBadWAPICredential(InfobloxException):
    message = _("Infoblox IPAM is misconfigured: "
                "infoblox_username and infoblox_password are incorrect.")


class InfobloxTimeoutError(InfobloxException):
    message = _("Connection to NIOS timed out")