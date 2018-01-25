# DHCP_121_macOS

## Overview
RFC 3442 / DHCP option 121 static route support for MacOS with installer.

##### Install instructions are near the end of this document in "To Install"

DHCP option 121 provides the option for clients to obtain static
route information from a DHCP server.  Unfortunately, older
versions of macOS do not natively handle option 121 routes in a stock
configuration.  This software is intended to alleviate this condition.

The software can be ran standalone (cron, etc.) or preferably via the
DHCP plist provided.  The installer will place the python script,
install the DHCP option in the request array and install the DHCP plist
so that the dhcp_121.py script is called at every interface status change,
such as when WiFi goes down or ethernet is plugged in.

El Capitan (a 2015 era version of macOS) brings in support for native
DHCP option 121 decoding and makes this software obsolete for its
intended use.

The data from a DHCP packet can be obtained well after the actual
transaction transpired.  The data includes the DHCP option codes present
in the response to this machines request.  If the DHCP option 121 is not
present, its likely due to the fact that this machine did not request
option 121.

Older versions of MacOS, such as Lion, require that the DHCP server be configured
to push option 121 without it being requested.  This can be configured in isc's
dhcpd like so:

#### force option 121 (hex 79) to be pushed in the reply:
option dhcp-parameter-request-list = concat(option dhcp-parameter-request-list, 79);

#### add_dhcp_request_option.py:
Option 121 can be requested if placed in the array of option codes
to request by the system.  The add_dhcp_request_option.py script is
written to place the option code safely into the system plist.  This
only works on particular versions of MacOS such as Yosemite, otherwise
see the note above about forcing option 121 in the DHCP replies from the 
dhcp server.

### Common use issue: en0 vs en1:
   en0 will be scanned first and will win.  This can be overriden with the
   the "nic" option in the override file, but its likely how most people
   things to behave in the event that they leave their wifi nic up when
   plugging ethernet in.

### OVERRIDE_FILE:
The override file can contain comments if the line starts with a #, but
should otherwise only specify an override value to be used in the event
that the default route is not on the interface with the DHCP response.

By default, /usr/local/etc does not exist as a directory, where it may
have to be created before the override file can exist.  Alternatively the
value of OVERRIDE_FILE can be modified for local installations.

By default the override file is defined as /usr/local/etc/dhcp_121_override

### override file variables:

##### nic:
    The DHCP nic is autodiscovered by way of default route.  The nic
    detected can be ignored in favor of the nic set via the override.
    nic = en1

##### gatewaycheck:
    disable verification of the gateway within a connected network
    by setting gatewaycheck to 0:
    gatewaycheck = 0

##### safe_nics:
    When the system has no DHCP lease (interface down, etc.)
    this script will be called in a manner that will clear any
    static route associated with an offline NIC that is showing
    in the routing table.
    safe_nics = "en0 en4"

##### forcenics:
    Similar to safe_nics, it may be desired to always clear the
    routes on a particular NIC type (fw0, the firewire NIC) as
    it will always have an active link state when not connected.
    forcenics = "en1 fw0"

##### staticroutes:
    Routes can be added by static configuration at interface bringup.
    If it is desired to truely force the route even when the gateway
    isn't reachable, disable the gatewaycheck (see gatewaycheck above)
    The final route doesnt require the semicolon, other routes do.
    forceroutes = "10.0.1.0/24 192.168.1.254; 10.0.2.0/25 192.168.1.253"


### To Install:
##### Client Side (on the Macintosh):
    - Run the installdhcp121 script as root with the "install" option.  
    -- the dhcp_121.py and add_dhcp_request_option.py scripts must be in the
       same directory

    -- the plist file doesnt need to be downloaded.  Its encoded
       in the installer.  the plist is included so folks can see
       what this script works with before use.

    At a high level does the following things:
      Copies the dhcp_121.py script to /usr/local/bin

      Creates the directory /usr/local/etc if it doesnt exist
         (so that the override file can be easily created)

      Inserts a DHCP option request code 121 into the existing
/System/Library/SystemConfiguration/IPConfiguration.bundle/Contents/Info.plist

      Places a DHCP plist file in /Library/LaunchDaemons

      Registers the DHCP plist

      Starts the DHCP plist which runs the dhcp_121.py script immediately

##### Server Side:
    - Configure option 121 responses, they will be requested by the client
      (see the section about add_dhcp_request_option.py)

### To Uninstall:
   Run the installdhcp121 script with the "uninstall" option.  It will
   deregister and remove the plist and removes the dhcp_121 python script.
   It will not remove /usr/local/etc or the option 121 request from the system
   plist as both improve the system regardless.

### To Use:
   Usage should be automatic for most environments and macintoshes.
   Once a NIC is enabled and takes on a DHCP lease, within a few seconds
   the routes should appear in the routing table.  Once the NIC is disabled,
   the routes will automatically be removed.
