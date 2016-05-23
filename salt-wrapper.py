#!/usr/bin/python

import sys
import argparse
import json
import salt.client
import requests
import socket
import random
import os
import yaml
import time
# disable ssl warnings...
#requests.packages.urllib3.disable_warnings()


parser = argparse.ArgumentParser(description='SaltStack HA helper script used \
            for registering and running orchestration agains multiple masters')
parser.add_argument('function', help='The function to be run (i.e. register or \
            orchestrate_heat or orchestrate_vra)')
parser.add_argument('username', help='The REST API endpoint authentication \
            username', default='', nargs='?')
parser.add_argument('password', help='The REST API endpoint authentication \
            password', default='', nargs='?')

parser.add_argument('-e', '--environment', help='The environment in which the \
            orchestration to be run (i.e. dev, test, prod, etc...)', default='base')
parser.add_argument('-a', '--automation', help='The pattern which to be run \
            (i.e. three_tier_lamp, etc...)')
parser.add_argument('-o', '--orchestration', help='The pattern orchestration \
            to be run (i.e. dev, test, prod, etc...)')
parser.add_argument('-p', '--pillar', help='The pillar data to use with the \
            orchestration', action='append', type=lambda kv: kv.split("="),
                    dest='pillar')
parser.add_argument('-w', '--wait_url', help='The WaitCondition URL to signal \
            after the orchestration is finished')
parser.add_argument('-t', '--token', help='The WaitCondition Authentication \
            Token to signal after the orchestration is finsihed')
parser.add_argument('-s', '--stack_id', help='The ID of the heat stack that \
            the orchestration should be run against')
parser.add_argument('-f', '--pillar_file', help='The file containing pillar \
            data to use with the orchestration (in YAML format)')
parser.add_argument('-z', '--sleep_time', help='How much time to sleep between \
            pushing stack pillar to git and executing orchestration \
            (in seconds)', default=60)
parser.add_argument('-d', '--port', help='The REST API endpoint port to use \
            (default is 8000)', default=8000)
parser.add_argument('-b', '--flask_port', help='The Flask Application port', \
            default=5000)

args = parser.parse_args()

# Some defaults
if os.name == 'nt':
  minion_opts = salt.config.minion_config('C:\salt\conf\minion')
else:
  minion_opts = salt.config.minion_config('/etc/salt/minion')

metadata_file = 'http://169.254.0.1:8080/metadata.yaml'


def __get_token__(master, username, password):
    print "Authenticating to:", master
    url = "https://{0}:{1}/login".format(master, args.port)
    headers = {
        "Accept": "application/json"
        }
    postdata = {
        "username": username,
        "password": password,
        "eauth": "pam"
    }

    try:
        req = requests.post(url=url, headers=headers,
                            data=postdata, verify=False)
        if req.status_code == 200:
            return req.json()["return"][0]["token"]
        else:
            print req.text
            return False
    except (requests.exceptions.RequestException) as e:
        print e.message
        return False


def __remove_token__(master, token):
    print "Deauthenticating"
    url = "https://{0}:{1}/logout".format(master, args.port)
    headers = {
        "Accept": "application/json",
        "X-Auth-Token": token
    }
    try:
        req = requests.post(url=url, headers=headers, verify=False)
        if req.status_code == 200:
            return True
        else:
            return False
    except (requests.exceptions.RequestException) as e:
        print e.message
        return False


def __accept_client__(master, token, minion):
        print "Accepting client key for:", minion
        url = "https://{0}:{1}/hook/minions/key/accept".format(master, args.port)
        headers = {
            "Accept": "application/json",
            "X-Auth-Token": token
        }
        postdata = {
            "minion": minion
        }
        try:
            req = requests.post(url=url, headers=headers,
                                data=postdata, verify=False)
            if req.status_code == 200:
                return True
            else:
                print req.text
                return False
        except (requests.exceptions.RequestException) as e:
            print e.message
            return False


def __check_client__(master, token, minion):
    print "Checking if client key for:", minion, "is accepted"
    url = "https://{0}:{1}/keys".format(master, args.port)
    headers = {
        "Accept": "application/json",
        "X-Auth-Token": token
    }
    try:
        req = requests.get(url=url, headers=headers, verify=False)
        if req.status_code == 200:
            if minion in req.json()["return"]["minions"]:
                return "accepted"
            elif minion in req.json()["return"]["minions_pre"]:
                return "unaccepted"
            else:
                return "nonexistent"
        else:
            print req.text
            return False
    except (requests.exceptions.RequestException) as e:
        print e.message
        return False


def __return_working_masters__(masters):
    working_masters = []
    for master in masters:
        try:
            sock = socket.create_connection((master, args.port), timeout=10)
            working_masters.append(master)
        except:
            print "Having troubles connnecting to", master
    return(working_masters)


def __inject_sys_state_if_needed(master):
    url = "http://{0}:{1}/add_sys_state/".format(master, args.flask_port)
    headers = {
        "Accept": "application/yaml"
    }
    postdata = {
        "pattern": args.automation,
        "orchestration": args.orchestration
    }

    try:
        req = requests.post(url=url, headers=headers,
                            json=postdata, verify=False)
        if req.status_code == 200:
            time.sleep(float(args.sleep_time))
            return True
        else:
            print req.text
            return False
    except (requests.exceptions.RequestException) as e:
        print e.message
        return False


def __run_heat_orchestration__(master, token, environment,
                               automation, orchestration):
    if args.pillar is not None:
        pillar = dict(args.pillar)
    else:
        pillar = 'None'
    if args.pillar_file is not None:
        __load_pillar_from_file__(args.pillar_file, master)
    __inject_sys_state_if_needed(master)
    if args.wait_url is not None:
        wait_url = args.wait_url
    if args.token is not None:
        wait_token = args.token
    else:
        wait_token = 'None'
    if args.stack_id is not None:
        stack_id = args.stack_id
    __refresh_stack_pillar__(master, token, args.stack_id)
    url = "https://{0}:{1}/hook/cmd/run_heat".format(master, args.port)
    headers = {
        "Accept": "application/json",
        "X-Auth-Token": token
    }
    postdata = {
        "environment": environment,
        "automation": automation,
        "orchestration": orchestration,
        "pillar": pillar,
        "wait_url": wait_url,
        "token": wait_token,
        "stack_id": stack_id
    }

    try:
        req = requests.post(url=url, headers=headers,
                            json=postdata, verify=False)
        if req.status_code == 200:
            return True
        else:
            print req.text
            return False
    except (requests.exceptions.RequestException) as e:
        print e.message
        return False


def __run_vra_orchestration__(master, token, environment,
                              automation, orchestration):
    if args.pillar is not None:
        pillar = dict(args.pillar)
    else:
        pillar = 'None'
    if args.pillar_file is not None:
        __load_pillar_from_file__(args.pillar_file, master)
    if args.stack_id is not None:
        stack_id = args.stack_id
    __refresh_stack_pillar__(master, token, args.stack_id)
    url = "https://{0}:{1}/hook/cmd/run_vra".format(master, args.port)
    headers = {
        "Accept": "application/json",
        "X-Auth-Token": token
    }
    postdata = {
        "environment": environment,
        "automation": automation,
        "orchestration": orchestration,
        "pillar": pillar,
        "stack_id": stack_id
    }

    try:
        req = requests.post(url=url, headers=headers,
                            json=postdata, verify=False)
        if req.status_code == 200:
            return True
        else:
            print req.text
            return False
    except (requests.exceptions.RequestException) as e:
        print e.message
        return False


def __load_pillar_from_file__(file, master):
    with open(file, 'r') as stream:
        pillar_dict = yaml.load(stream)
    url = "http://{0}:{1}/create_pillar_data/".format(master, args.flask_port)
    headers = {
        "Accept": "application/yaml"
    }
    postdata = {
        "stackid": args.stack_id,
        "env_var": args.environment,
        "pillardata_dict": pillar_dict,
        "pattern": args.automation
    }

    try:
        req = requests.post(url=url, headers=headers,
                            json=postdata, verify=False)
        if req.status_code == 200:
            time.sleep(float(args.sleep_time))
            return True
        else:
            print req.text
            return False
    except (requests.exceptions.RequestException) as e:
        print e.message
        return False


def __refresh_stack_pillar__(master, token, stack_id):
    # sends a call to the salt/netapi/hook/refresh_pillar reactor
    # this refreshes pillar data for the whole stack

    # wait for the previous reactor (fileserver.update) to finish
    time.sleep(float(args.sleep_time))
    print "Sendind refresh pillar signal to master: " + master
    print "Stack id: " + stack_id
    url = "https://{0}:{1}/hook/refresh_pillar".format(master, args.port)
    headers = {
        "Accept": "application/json",
        "X-Auth-Token": token
    }
    postdata = {
        "stack_id": stack_id
    }

    try:
        req = requests.post(url=url, headers=headers,
                            data=postdata, verify=False)
        if req.status_code == 200:
            # wait for reactor to finish
            time.sleep(float(args.sleep_time))
            return True
        else:
            print req.text
            return False
    except (requests.exceptions.RequestException) as e:
        print e.message
        return False

def __fetch_metadata__():
    print "Fetching metadata"
    url = metadata_file
    try:
        req = requests.get(url=url, verify=False)
        if req.status_code == 200:
          metadata = yaml.load(req.content)
          args.username = metadata["salt_api_user"]
          args.password = metadata["salt_api_password"]
          args.port =  metadata["salt_api_port"]
        else:
            print req.text
            return False
    except (requests.exceptions.RequestException) as e:
        print e.message
        return False

def main():
    '''main function'''

    if args.username == '' or args.password == '':
      print "Username and/or password are empty, fetching metadata file"
      __fetch_metadata__()

    if args.function == 'register':
        print 'Registering...'
        working_masters = __return_working_masters__(minion_opts['master'])
        for master in working_masters:
            token = __get_token__(master, args.username, args.password)
            if __check_client__(master, token,
                                minion_opts['id']) == "accepted":
                print 'Minion key is accepted'
            elif __check_client__(master, token,
                                  minion_opts['id']) == "unaccepted":
                __accept_client__(master, token, minion_opts['id'])
            else:
                print "Minion key is not yet registered"
            __remove_token__(master, token)

    elif args.function == 'orchestrate_heat':
        print 'Orchestrating...'
        master = random.choice(__return_working_masters__
                               (minion_opts['master']))
        token = __get_token__(master, args.username, args.password)
        __run_heat_orchestration__(master, token, args.environment,
                                   args.automation, args.orchestration)
        __remove_token__(master, token)

    elif args.function == 'orchestrate_vra':
        print 'Orchestrating...'
        master = random.choice(__return_working_masters__
                               (minion_opts['master']))
        token = __get_token__(master, args.username, args.password)
        __run_vra_orchestration__(master, token, args.environment,
                                  args.automation, args.orchestration)
        __remove_token__(master, token)
    else:
        print 'Try again...'
        parser.print_help()
        sys.exit(2)

if __name__ == '__main__':
    main()

