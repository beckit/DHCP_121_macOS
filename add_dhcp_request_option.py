#!/usr/bin/env python

"""
Add or remove a DHCP option from the system IPConfiguration.bundle/Info.plist

The modified plist setting requires rebooting to take effect.
"""

import os
import sys


PATH = '/System/Library/SystemConfiguration/IPConfiguration.bundle/Contents'
FILE_NAME = 'Info.plist'
FILE = PATH + '/' + FILE_NAME

DEFAULT_OPTION_CODE = '121'


def check_root():
    """
    Exit the program with an error code if the current UID is not 0
    """
    if not os.geteuid() == 0:
        sys.exit("Exiting: root permissions required")


def get_argv():
    """
    Returns any sys.argv data.  The only option this takes is the
    single DHCP option to write into the plist.
    """
    if len(sys.argv) > 1:
        option_code = sys.argv[1]
    else:
        option_code = DEFAULT_OPTION_CODE
    return option_code


def get_file_handle(filename, mode=''):
    """
    Returns a file handle
    """
    # read only if mode isnt specified
    mode = mode or 'r'
    try:
        file_handle = open(filename, mode)
    except IOError:
        sys.exit('Issue in opening file handle for: %s' % filename)

    return file_handle


def open_plist_file(filename):
    """
    Returns a readlines() list of file data
    """
    plist_file = get_file_handle(filename)
    try:
        file_data = plist_file.readlines()
    except IOError:
        sys.exit('Cannot read file: %s' % filename)

    finally:
        plist_file.close()

    return file_data


def process_plist_file(filename, option_code):
    """
    Read the plist file and parse
    for the option code

    Returns a writelines() compatible list with the new plist
    and a variable that indicates if the file needs to
    be written to disk as there was a change
    """
    file_data = open_plist_file(filename)

    option_code = option_code or '121'

    insert_key = '<integer>%s</integer>\n' % option_code

    dhcp_key_in_file = False
    option_in_plist = False
    end_of_array = False
    file_needs_change = False
    tab_offset = 0
    new_file_data = []
    for line in file_data:
        if dhcp_key_in_file and not option_in_plist and not end_of_array:
            # calculated the tab offset by splitting the line on the first <
            # and running len on the leftmost chunk of whitespace
            if '<integer>' in line and '</integer>' in line and not tab_offset:
                tab_offset = len(line.split('<')[0])
            # prevent an existing option_code entry from duplicates:
            if '<integer>%s</integer>' % option_code in line:
                option_in_plist = True
            # the end of the array must be reached to determine
            # if option_code is in the array
            if '</array>' in line:
                end_of_array = True
            # add a new option_code entry to the file only
            # if the option doesnt exist, the end of the array
            # has been seen and a tab offset has been calculated
            if not option_in_plist and end_of_array and tab_offset:
                new_key = tab_offset * '\t' + insert_key
                new_file_data.append(new_key)
                file_needs_change = True
        if '<key>DHCPRequestedParameterList</key>' in line:
            dhcp_key_in_file = True

        # always put the line "back" into the new file:
        new_file_data.append(line)

    return new_file_data, file_needs_change


def write_plist_file(filename, file_data):
    """
    Writes the specified file, overwriting a file with the same name
    """
    plist_file = get_file_handle(filename, mode='w')
    try:
        plist_file.writelines(file_data)

    except IOError:
        sys.exit('Cannot Create File: %s' % filename)

    finally:
        plist_file.close()
        print 'file written to disk: %s' % filename


def main():
    """
    Attempts to safely add an integer to an array within a plist
    and then restarts the plist
    """
    # Exit if not executed wtih root permissions
    check_root()

    # was an option specified?
    option_code = get_argv() or DEFAULT_OPTION_CODE

    # filename is default
    filename = FILE

    # parse the existing plist file and get the control keys
    new_file_data, file_needs_change = process_plist_file(filename, get_argv())

    # only write out a new file if the option wasnt already present
    if file_needs_change:
        if new_file_data:
            write_plist_file(filename, new_file_data)
            print 'Reboot to have DHCP requests with option %s' % option_code


if __name__ == "__main__":
    main()
