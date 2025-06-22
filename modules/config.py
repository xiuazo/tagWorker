import yaml
from pytimeparse2 import parse
from modules.logger import logger

CONFIG_FILE = 'config/config.yml'

class Config:
    def __init__(self, config_file = CONFIG_FILE):
        logger.info(f'%-10s - Reading config file', 'GLOBAL')
        with open(config_file, "r") as ymlfile:
            config_dict = yaml.safe_load(ymlfile)

        for key, value in config_dict.items():
            setattr(self, key, value)

        self.trackers_HR_rules = {}
        for tracker, config in self.tracker_details.items():
            hr_config = config.get('HR')

            if hr_config and len(hr_config) > 0:
                required_time = hr_config[0]
                ratio = hr_config[1] if len(hr_config) > 1 else None
                allowed_percent = hr_config[2] if len(hr_config) > 2 else None

                self.trackers_HR_rules[tracker] = [
                    parse(required_time) + parse(self.extra_seed_time),
                    ratio + self.extra_ratio if ratio is not None else None,
                    allowed_percent
                ]
            else:
                # Si 'HR' no está presente o está vacío, maneja el caso
                self.trackers_HR_rules[tracker] = [0, None, None]

# current_dir = os.path.dirname(os.path.abspath(__file__))
# config_file = os.path.join(current_dir, CONFIG_FILE)
# config_file = os.path.normpath(config_file)
