#!/usr/bin/env python
"""
    dhcp_121.py is a DHCP Option 121 parsing script designed to be called
    by a MacOS plist (launchd controlled).  It parses the static routes and
    sets them where the OS doesn't natively set it otherwise, which comes
    in El Capitan.

    The data from a DHCP packet can be obtained well after the actual
    transaction transpired.  The data includes the DHCP option codes present
    in the response to this machines request.  If the DHCP option 121 is not
    present, its likely due to the fact that this machine did not request
    option 121.  There is a method of adding in option 121 to the systems
    DHCP request, see the add_dhcp_request_option.py section of the readme

"""
import os
import platform
import re
import socket
import struct
import subprocess
import sys

# pkg_resources depends on at least one of the above imports
# so import it afterwards
import pkg_resources

# OVERRIDE_FILE:
# The override file can contain comments if the line starts with a #, but
# should otherwise only specify an override value to be used in the event
# that the default route is not on the interface with the DHCP response.
#
# By default, /usr/local/etc does not exist as a directory, where it may
# have to be created before the override file can exist.  Alternatively the
# value of OVERRIDE_FILE can be modified for local installations.
#
#
# The override works with these variables:
#
# nic:
#     The DHCP nic is autodiscovered by way of default route.  The nic
#     detected can be ignored in favor of the nic set via the override.
#     nic = en1
#
# gatewaycheck:
#     disable verification of the gateway within a connected network
#     by setting gatewaycheck to 0:
#     gatewaycheck = 0
#
# safe_nics:
#     When the system has no DHCP lease (interface down, etc.)
#     this script will be called in a manner that will clear any
#     static route associated with an offline NIC that is showing
#     in the routing table.
#     safe_nics = "en0 en4"
#
# forcenics:
#     Similar to safe_nics, it may be desired to always clear the
#     routes on a particular NIC type (fw0, the firewire NIC) as
#     it will always have an active link state when not connected.
#     forcenics = "en1 fw0"
#
# staticroutes:
#     Routes can be added by static configuration at interface bringup.
#     If it is desired to truely force the route even when the gateway
#     isn't reachable, disable the gatewaycheck (see gatewaycheck above)
#     The final route doesnt require the semicolon, other routes do.
#     forceroutes = "10.0.1.0/24 192.168.1.254; 10.0.2.0/25 192.168.1.253"
OVERRIDE_FILE = '/usr/local/etc/dhcp_121_override'


def check_for_override_file():
    """
    Checks a file for a specified override value of the NIC
    to monitor for DHCP response packet data.

    Returns the NIC to check as a string
    """
    # assume the file isnt present for normal operation
    file_data = ''
    if os.path.isfile(OVERRIDE_FILE) and os.access(OVERRIDE_FILE, os.R_OK):
        file_handle = open(OVERRIDE_FILE)
        try:
            file_data = file_handle.readlines()
        finally:
            file_handle.close()

    # grab the default nic for the default
    nic = ''
    force_nics = ''
    safe_nics = ''
    static_routes = ''

    # check that the gateway is locally reachable by default
    gatewaycheck = True

    if file_data:
        # always report the file and its NIC if it was used
        print '[OVERRIDE] Found override file: %s' % OVERRIDE_FILE

    for line in file_data:
        # comments are supported if the line begins with an octothorpe
        if not re.match(r'^\#', line):
            # regex note:
            # (\W){0,} = match 0 or more whitespace characters

            # the last nic specified will be set:
            if re.match(r'(\W){0,}nic(\W){0,}=(\W){0,}', line):
                nic = line.split('=')[1].strip()
                print '[OVERRIDE] dhcp_121 will monitor NIC: %s' % nic

            # set gateway check to 0 or False to disable
            if re.match(r'(\W){0,}gatewaycheck(\W){0,}=(\W){0,}', line):
                gatewaycheck = line.split('=')[1].strip()
                print '[OVERRIDE] disabling gateway check'

            # set route-safe NIC for nics that can exist with routes
            # in the event that the DHCP nic goes offline.
            if re.match(r'(\W){0,}safe_nics(\W){0,}=(\W){0,}', line):
                safe_nics = line.split('=')[1].strip()
                print '[OVERRIDE] ignoring routes on: %s' % safe_nics

            # set static routes "dynamically"
            if re.match(r'(\W){0,}staticroutes(\W){0,}=(\W){0,}', line):
                static_routes = line.split('=')[1].strip()
                print '[OVERRIDE] ignoring routes on: %s' % safe_nics

    return nic, gatewaycheck, force_nics, safe_nics, static_routes


def check_root():
    """
    Exit the program with an error code if the current UID is not 0
    """
    if not os.geteuid() == 0:
        sys.exit("Exiting: root permissions required")


def check_version():
    """
    El Capitan brings in native macOS DHCP Option 121 parsing!
    (and makes this software obsolete)

    This prevents upgraded systems from having issues.  This
    script can be safely removed after upgrading to El Capitan
    or later.
    """
    if sys.platform != 'darwin':
        sys.exit('macOS required but not detected')
    if pkg_resources.parse_version(platform.release()) >= \
            pkg_resources.parse_version('15.6.0'):
        sys.exit('Exiting: DHCP option 121 is built into this OS')


def clear_routes(forcenics, safenics):
    """
    Clears out all static routes associated with NICs that are in a down state
    and not on the safenics override list.

    If the NIC isnt down but is specified on the forcenics override, that NICs
    routes will be deleted.
    """
    # Get routing table with masks
    routes = get_route_table_with_masks()

    # Build up a list of nics
    nics = []
    interfaces = get_ipv4_interfaces()
    for line in interfaces.splitlines():
        if re.match(r'^\w+: ', line):
            nics.append(line.split(':')[0].strip())

    # Build up a list of nics to clear the routes from
    clear_nics = []
    for nic in forcenics.split():
        clear_nics.append(nic.strip())

    # Build up a list of nics to ignore routes on from
    # an override
    safenics_list = []
    for nic in safenics.split():
        safenics_list.append(nic.strip())

    # Remove the routes from the list of clear_nics if the nic
    # isnt in the safenic_list and the nic is down
    for nic in nics:
        if nic not in safenics_list:
            # should match "None" and "not set"
            if re.match('[Nn][Oo]', get_hardware_link_state(nic)[:2]):
                if nic not in clear_nics:
                    clear_nics.append(nic)

    # For each nic in the clear_nics list, go through the route table
    # and remove the nics associated routes
    for nic in clear_nics:
        for route in routes:
            if nic == route[3]:
                route_cmd(route=[route[0], route[1], route[2]],
                          routeverb='delete')


def decode_option_121(option_data):
    """
    This function decodes the DHCP option 121 data format
    into a list of tuples in the form of (netmask, subnet_route, gateway)

    DHCP option 121 data comes across from the output of
    'ipconfig getpacket <interface>' in the following format:
    1st entry - line number
    2nd entry - netmask in bits
    3rd entry - 1st byte of subnet
    4th entry - Nth byte of subnet or first byte of gateway
    Nth entry - last byte of gateway, gateway always has 4 bytes
    N+1 entry - second netmask in bits
    N+2 entry - 1st byte of second subnet
    N+Nth entry - last byte of second subnet or first byte of second gateway
    N+Nth entry - second gateway always has four bytes
    last entry on line - "...." periods representing byte count

    Example output from "ipconfig getpacket en1" with multiple subnets on my
    eldery macbook pro:
    ...
    option_121 (opaque):
    0000  18 c0 a8 01 c0 a8 00 1d  18 c0 a8 02 c0 a8 00 1d  ................
    0010  18 c0 a8 03 c0 a8 00 1d  08 05 c0 a8 00 fe 18 c0  ................
    0020  a8 04 c0 a8 00 1d 18 c0  a8 05 c0 a8 00 1d 18 c0  ................
    0030  a8 06 c0 a8 00 1d 11 0a  02 f0 c0 a8 0a c8        ..............

    end (none):
    """
    # The byte_stream is a list that will be filled in with just the data
    # bytes containing network mask, subnet and gateway information:
    byte_stream = []

    # Fill the byte_stream only with right sized byte representations from
    # the output parsed line by line - filter out the line numbers and byte
    # count dots
    for line in option_data:
        splitted = line.split()
        for entry in splitted:

            # Only append entries two characters wide that were surrounded by
            # spaces
            if len(entry) < 3:
                # Guard against including the byte count dots when only two
                # data bytes are present
                if entry is not '..':
                    byte_stream.append(entry)

    # By default a subnet_mask is not assumed to be set:
    subnet_mask = 0

    # By default there is no subnet specified:
    net_bytes = 0

    # A gateway will always be specified with four bytes:
    gateway_bytes = 4

    # Pattern build up holding lists:
    dot_subnet = []
    dot_gateway = []

    # This list will be returned by the function
    routes = []

    # Parse the byte stream one byte at a time:
    for byte in byte_stream:
        # Convert the bytes to decimal
        byte = int(byte, 16)

        # If the subnet_mask is set then we're looking for the subnet and
        # gateway bytes that must appear after
        if subnet_mask:
            if net_bytes:
                dot_subnet.append(str(byte))
                net_bytes -= 1

            # Once the net_bytes counter is depleted we know the next
            # bytes in the stream represent the gateway
            else:
                dot_gateway.append(str(byte))
                gateway_bytes -= 1

            # Once the gateway_bytes are taken from the stream a complete
            # route is present and stored.  There are potentially additional
            # routes to process so it must reset the control logic variables
            # for the next route to be determined.
            if not gateway_bytes:
                while len(dot_subnet) < 4:
                    dot_subnet.append('0')
                subnet = '.'.join(dot_subnet)
                gateway = '.'.join(dot_gateway)
                routes.append((subnet, subnet_mask, gateway))

                # Reset the following for the next bytes in the stream:
                subnet_mask = 0
                dot_subnet = []
                dot_gateway = []
                gateway_bytes = 4
        else:
            # Subnet_mask is determined by bit position,
            # where its always leading so as to determine
            # the byte positions for the subnet and gateway
            subnet_mask = byte

            # The number of bytes following the subnet entry
            # that represent the subnet and gateway
            net_bytes = subnet_mask / 8
    return routes


def get_default_nic():
    """
    Returns the NIC with the default route, which is usually where the DHCP
    response packet can be found
    """
    # by default, check en1 (Macbook Pro, etc.)
    nic = 'en1'

    route_table = get_route_table()

    # check the route_table for a default route and parse the nic
    for line in route_table.splitlines():
        # assumes one default route exists:
        if re.search('^default', line):
            nic = line.split()[5]
    return nic


def get_hardware_link_state(nic):
    """
    Report the hardware link state of a specified nic

    nic:
        specify a device name, such as 'en1'

    Returns the link state as a string, which was reported from networksetup
    """
    # get the media state of the specific nic
    cmd = 'networksetup -getmedia %s' % nic

    try:
        stdout = subprocess.check_output(cmd.split())
    except subprocess.CalledProcessError:
        stdout = ''

    state = ''
    if stdout:
        for line in stdout.splitlines():
            if re.search('^Active: ', line):
                state = line.split()[1].strip()
    return state


def get_ip_addresses(interface):
    """
    Determine the IPv4 addreses for the specified interface

    interface:
        the macOS network interface name, such as 'en1' for /dev/en1

    Returns a list of "ip address, netmask" tuples
    """
    cmd = '/sbin/ifconfig %s inet' % interface
    stdout = subprocess.check_output(cmd.split())
    addresses = []
    for line in stdout.splitlines():
        inet = re.search(r'inet ((?:[0-9]{1,3}\.){3}[0-9]{1,3}) '
                         r'netmask (0x[f0]{8}) '
                         r'broadcast ((?:[0-9]{1,3}\.){3}[0-9]{1,3})',
                         line)
        if inet:
            ip_address = inet.groups()[0]
            mask = bin(int(inet.groups()[1], 0)).count('1')
            broadcast = inet.groups()[2]
            addresses.append((ip_address, mask, broadcast))
    return addresses


def get_ipv4_interfaces():
    """
    Returns a list of system networking interfaces
    """
    # show all the interfaces and ipv4 networking info
    cmd = 'ifconfig -a inet'
    return subprocess.check_output(cmd.split())


def get_ipv4_routes(route_table):
    """
    The route table has several types of routes in it,
    this will filter out all but the ipv4 routes.

    The filters out the default route

    Returns a list of lists (line by line route output)
    """
    only_ipv4_routes = []
    for item in route_table:
        if len(item) >= 6:
            if re.match(r'\d+\.\d+\.\d+\.\d+', item[1]):
                if 'default' not in item[0]:
                    only_ipv4_routes.append(item)
    return only_ipv4_routes


def get_option(packet, option_code):
    """
    Parses for the option_code's data from ipconfig output

    packet:
        the packet data from "ipconfig getpacket"

    option_code:
        the DHCP option code to parse, for example "option_121"

    Returns a list populated with each line of packet data corresponding to
    the DHCP option code.
    """
    option = False
    option_data = []
    for line in packet.splitlines():
        if option:
            if line:
                option_data.append(line)
            else:
                option = False

        # this has to come after the decoder for the option line
        if option_code in line:
            option = True
    return option_data


def get_packet(interface):
    """
    Retrieve the DHCP packet information to obtain the option data

    See the uppermost docstring for information on DHCP option 121
    not appearing in the responses due to the fact that they are not
    requested in older client versions.

    interface:
        the macOS network interface name, such as 'en1' for /dev/en1

    Returns the getpacket data for the interface as a list of strings
    """
    cmd = '/usr/sbin/ipconfig getpacket %s' % interface
    try:
        stdout = subprocess.check_output(cmd.split())
    except subprocess.CalledProcessError:
        stdout = ''
    return stdout


def get_route_table():
    """
    Returns a routing table
    """
    # only show the ipv4 routing table without name resolution:
    cmd = 'netstat -f inet -rn'
    return subprocess.check_output(cmd.split())


def get_route_table_with_masks():
    """
    Return a route table with the subnet routes 0 padded.  Subnets without
    a bit
    """
    # Parse the netstat output into a split line by line list of lists
    route_table = [item.split() for item in get_route_table().splitlines()]

    # Build a list of only the IPv4 static routes
    only_ipv4_routes = get_ipv4_routes(route_table)

    # Build the final list in presentable view
    routes = []
    for route in only_ipv4_routes:
        # Subnet, mask, gateway and interface
        if '/' in route[0]:
            target, mask = route[0].split('/')
        else:
            target = route[0]
            mask = ''

        # Pads out the route entries as an IP (target) within
        # the subnet.
        while target.count('.') < 3:
            target = target + '.0'

        if not mask:
            bit_subnet = ip_address_to_32bit(target)
            if bit_subnet[:1] == '0':
                mask = '8'
            if bit_subnet[:2] == '10':
                mask = '16'
            if bit_subnet[:3] == '11':
                mask = '24'

        # The new routing moves the old fields over except the padded address
        # and adds in the bits field to preserve the subnet information that
        # may have been removed from the old address in route[0]
        routes.append([target, mask, route[1], route[5]])

    return routes


def ip_address_to_32bit(address):
    """
    Returns IP address converted to a "32bit" long binary string
    127.0.0.1 will be returned as 01111111000000000000000000000001
    """
    binary = bin(struct.unpack('!L', socket.inet_aton(address))[0])
    # Remove the leading '0b' text:
    binary = binary[2:]
    # Pad the number's string until it is 32 characters wide
    while len(binary) < 32:
        binary = '0' + binary
    return binary


def route_cmd(route, routeverb=''):
    """
    Adds a specified route with the UNIX route command

    route - a tuple with three fields:
        subnet - network address to route
        mask - length of subnet mask in bits (24, etc.)
        gateway - the next hop router for the packet

    UNIX Errors:
    "route: writing to routing socket: File exists"

        This does not check if a current route exists, which will cause a UNIX
        error to display.  This can usually be ignored as the route was likely
        set from the last time the interface was enabled.


    "add net 192.168.1.0: gateway 192.168.0.1: File exists"

        If there is a conflicting route present, it will display a similar
        error directly after the routing sockets File exists error is displayed
        for the same route add operation.

        Simply remove the conflicting static routes as need be per the desired
        network topology, disable and enable the interface again (to run this
        script) and the DHCP specified static routes will populate as expected.

    Returns the stdout from the operation
    """
    routeverb = routeverb or 'add'
    subnet = route[0]
    mask = route[1]
    gateway = route[2]
    cmd = 'route %s %s/%s %s' % (routeverb, subnet, mask, gateway)
    return subprocess.check_output(cmd.split())


def set_routes(routes, addresses, gatewaycheck, static_routes):
    """
    Checks to see if the specified route should be added to the UNIX routing
    table.

    Returns a dictionary of the stdouts from each route attempted
    """
    stdouts = []

    current_routes = get_route_table_with_masks()

    # Add in the forceroutes from the override file:
    if static_routes:
        for static in static_routes.split(';'):
            subnet = static.split('/')[0].strip()
            mask = (static.split('/')[1].strip()).split()[0]
            gateway = (static.split('/')[1].strip()).split()[1]
            routes.append([subnet, mask, gateway])

    for route in routes:
        set_route = False

        # Check if the gateway is on a reachable subnet before
        # attempting to add the route
        if gatewaycheck:
            for ip_address, mask, _ in addresses:
                if subnet_check(mask, ip_address, route[2]):
                    set_route = True
        else:
            set_route = True

        # Determine if there is an existing route before
        # trying to add it, which would likely fail if attempted
        for current in current_routes:
            if current[0] == route[0]:
                if current[1] == route[1]:
                    set_route = False

        if set_route:
            stdouts.append(route_cmd(route))

    return stdouts


def subnet_check(netmask_bits, ip_address, target):
    """
    Check if the specific gateway is within the network that the IP and Mask
    represents.

    netmask_bits:
         Number of bits in the netmask

    ip_address:
         A dotted quad string with any IP in the subnet to be checked

    target:
         A dotted quad string representing the target to check

    Returns True only if the specified target is within the calculated subnet
    range
    """
    ip_decimal = struct.unpack('!L', socket.inet_aton(ip_address))[0]
    target_decimal = struct.unpack('!L', socket.inet_aton(target))[0]
    netmask_decimal = (0xFFFFFFFF >> int(netmask_bits)) ^ 0xFFFFFFFF
    return ip_decimal & netmask_decimal == target_decimal & netmask_decimal


def main():
    """
    Attempts to automatically determine the interface where DHCP responses
    are received, then looks to decode DHCP option 121 static route
    statements and sets them as appropriate if and only if an existing
    NIC is configured to reach each specified routes gateway.
    """
    # Exit if the version is new enough to have option 121 support
    check_version()

    # Exit if not executed wtih root permissions
    check_root()

    # Override Variables, see the OVERRIDE_FILE comment at the top
    # of this code for explanation
    nic, gatewaycheck, safenics, forcenics, static_routes = \
        check_for_override_file()

    # if the override nic isnt present, determine the NIC with the
    # DHCP response based upon the default route.
    if not nic:
        nic = get_default_nic()

    # Retrieve the nic IP addressing information
    addresses = get_ip_addresses(nic)

    # Retrieve the DHCP response packet information for the NIC
    packet = get_packet(nic)
    if packet:

        # Retrieve the option_121 data from the DHCP options
        option_data = get_option(packet, 'option_121')

        # Decodes any option_121 data into route statements
        routes = decode_option_121(option_data)

        # Stale static routes must be cleared out before
        # attempting to add any
        preforcenics = forcenics
        if nic not in preforcenics:
            preforcenics = preforcenics + ' ' + nic
        clear_routes(preforcenics, safenics)

        # Attempt to add the derived static routes
        set_routes(routes, addresses, gatewaycheck, static_routes)
    else:
        # Clear the routes on any down NIC, inclusive of any down DHCP
        # interface (When WiFi drops, the routes are removed)
        clear_routes(forcenics, safenics)


if __name__ == "__main__":
    main()
