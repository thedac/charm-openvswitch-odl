import subprocess

from charmhelpers.core.hookenv import cached


def set_manager(connection_url):
    '''Configure the OVSDB manager for the switch'''
    subprocess.check_call(['ovs-vsctl', 'set-manager', connection_url])


@cached
def _get_ovstbl():
    ovstbl = subprocess.check_output(['ovs-vsctl', 'get',
                                      'Open_vSwitch', '.',
                                      '_uuid']).strip()
    return ovstbl


def set_config(key, value, table='other_config'):
    '''Set key value pairs in the other_config table'''
    subprocess.check_call(
        ['ovs-vsctl', 'set',
         'Open_vSwitch', _get_ovstbl(),
         '{}:{}={}'.format(table, key, value)]
    )
