#!/usr/bin/env python3
import os
import re
import sys
import time
from ruamel.yaml import YAML
import json
import paho.mqtt.client as mqtt
import logging

yaml = YAML()
yaml.preserve_quotes = True

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stderr))

# Home Assistant base path
hass_path = "core"

# Configure the path to home assistant here
sys.path.append(hass_path)

# Core config, to take mqtt values from
core_config_file = hass_path + "/config/.storage/core.config_entries"

# File to add entities to (read only)
hass_config_file = hass_path + '/config/configuration.yaml'

# MQTT topic the original configs are pushed to
mqtt_config_topic = 'homeassistant/switch/#'

mappings = {
    'RF2_0_0_28226590': ('light-dimmer.yaml', 'Stalamp'),
    'RF2_1_0_28226590': ('light.yaml', 'Buitenlampen Achter'),
    'RF4_1_0_28226590': ('light.yaml', 'Buitenlamp Voor'),
    'RF2_5_0_28226590': ('light-dimmer.yaml', 'Gaaslamp'),
    'RF2_6_0_28226590': ('light.yaml', 'Meloenlamp'),
    'RF2_7_0_28226590': ('light.yaml', 'Marokkaanse lamp'),
    'RF2_8_0_28226590': ('cover.yaml', 'Gordijnen achter'),
}

from homeassistant.components.mqtt.abbreviations import *

def interact(_loc):
    import code
    import readline
    import rlcompleter

    vars = globals()
    vars.update(_loc)

    readline.set_completer(rlcompleter.Completer(vars).complete)
    readline.parse_and_bind("tab: complete")
    code.InteractiveConsole(vars).interact()

def sub_get(n, *args, default=None, abbr=ABBREVIATIONS):
    if len(args) == 0:
        return n

    key = args[0]
    if key in abbr:
        key = abbr[key]

    if n is not None and key in n:
        return sub_get(n[key], *args[1:], default=default)

    return default

with open(core_config_file) as f:
    hass_config = yaml.load(f)
    mqtt_config = list(filter(lambda e: e['domain'] == 'mqtt', hass_config['data']['entries']))[0]['data']

def on_connect(client, userdata, flags, rc):
    logger.info("Connected with result code "+str(rc))
    client.subscribe(mqtt_config_topic)

mqtt_devices = []
def on_message(client, userdata, msg):
    #print(msg.topic+" "+str(msg.payload))
    mqtt_devices.append(msg.payload.decode('utf-8'))

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.username_pw_set(mqtt_config['username'], mqtt_config['password'])
client.connect(mqtt_config['broker'], mqtt_config['port'])
client.loop_start()
logger.info("Waiting...")
time.sleep(.1)
client.loop_stop()
logger.info("Waited")

#interact(locals())

re_holder = re.compile('{{{(\w+)}}}')
def replaceholders(obj, values):
    if isinstance(obj, list):
        ret = []
        for elem in obj:
            ret.append(replaceholders(elem, values))
        obj = ret

    if isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = replaceholders(v, values)

    if isinstance(obj, str):
        #print("STR:",type(obj), obj)
        m = re_holder.search(obj)
        while m:
            holder = m.group(1)
            #print("holder:", holder)
            if holder in values:
                typ = type(obj)
                #print("typ:", typ)
                #print(holder, values[holder])
                start = m.start(0)
                end = m.end(0)
                obj = typ(obj[:start] + str(values[holder]) + obj[end:])
            else:
                raise Exception("Unknown placeholder:", holder)
            #print("obj:", type(obj), obj)
            m = re_holder.search(obj)

    return obj

if os.path.isfile(hass_config_file):
    with open(hass_config_file) as f:
        config = yaml.load(f)
else:
    config = {}

re_kaku_id = re.compile(r'RF2_(\d+)_(\d+)_(\d+)')
for mqtt_info in mqtt_devices:
    dev = json.loads(mqtt_info)
    #print(dev)
    if dev['name'] in mappings:
        template_file, new_name = mappings[dev['name']]
        #print(dev['name'], template_file)

        with open(template_file) as f:
            template = yaml.load(f)

            m = re_kaku_id.match(dev['name'])
            if not m:
                raise Exception("Unsupported name format, expected (RF2_x_x_xxxxxxxx):", dev['name'])

            variables = {
                'rf2_unit': m.group(1),
                'rf2_group_bit': m.group(2),
                'rf2_address': m.group(3),
                'uniq_id': dev['uniq_id'],
                'name': new_name
            }

            dev_config = replaceholders(template, variables)

            if not isinstance(dev_config, dict) or len(dev_config) != 1:
                raise Exception("Template should return a map with a single key (e.g. light, switch, cover)")

            for hass_class, entities in dev_config.items():
                if hass_class not in config:
                    config[hass_class] = []

                for entity in entities:
                    uniq_id = entity['unique_id']

                    old_entities = list(filter(lambda e: sub_get(e[1], 'unique_id') == uniq_id, enumerate(config[hass_class])))

                    if len(old_entities) > 1:
                        raise Exception("Unsupported configuration.yaml. Multiple devices with the same unique_id:" + uniq_id)

                    if len(old_entities) > 0:
                        idx, _ = old_entities[0]
                        config[hass_class][idx] = entity
                    else:
                        config[hass_class].append(entity)

yaml.dump(config, sys.stdout)
