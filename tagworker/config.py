import yaml

class GlobalConfig:
    _config = None
    DEFAULTS = {
        "app": {
            "tagging_schedule_interval": 30,
            "disktasks_schedule_interval": "10m",
            "fullsync_interval": "60m",
            "share_limits_tag_prefix": "~sl.",
            "dupes": {
                "enabled": True,
                "tag": "~DUPE"
            },
            "issue": {
                "tag": "@issue"
            },
            "lowseeds": {
                "min_seeds": 3,
                "tag": "~lowSeeds"
            },
            "huno_tag_prefix": "!HUNO_",
            "noHL": {
                "tag": "~noHL",
                "categories": [
                    "movies",
                    "tv",
                    "audiobooks",
                    "xseed"
                ]
            },
            "prune_orphaned_time": "2w",
            "noTMM": {
                "auto_enable": False,
                "tag": "~noTMM",
                "ignored_tags": [],
                "ignored_categories": [
                    "cross-seed-link",
                ]
            },
            "tag_renamer": {
                "cross-seed": "xs",
                "sonarr.cross-seed": "xs.tv",
                "tv.cross-seed": "xs.tv",
                "radarr.cross-seed": "xs.movies",
                "movies.cross-seed": "xs.movies",
            },
            "HR": {
                "tag": "~H&R",
                "extra_seed_time": "5h",
                "extra_ratio": 0.1,
                "exclude_xseed": True,
                "autostart": False
            }
        },
        "clients": {
            "media": {
                "enabled": True,
                "url": "http://localhost:8080",
                "user": "admin",
                "password": "adminadmin",
                "local_instance": True,
                "dryrun": False,
                "commands": {
                    "tag_issues": True,
                    "tag_rename": True,
                    "tag_trackers": True,
                    "tag_HR": True,
                    "tag_lowseeds": False,
                    "tag_HUNO": True,
                    "scan_no_tmm": True,
                    "share_limits": True,
                    "tag_noHL": True,
                    "clean_orphaned": True,
                    "prune_orphaned": True,
                    "delete_empty_dirs": True
                },
                "folders": {
                    "root_path": "/mnt/data/torrents",
                    "orphaned_path": "/mnt/data/torrents/.orphaned_data"
                },
                "translation_table": {
                    "/data": "/mnt/data"
                },
                "share_limits": {
                    "noDUPE": {
                        "include_all_tags": ["~DUPE"],
                        "max_seeding_time": 0
                    },
                    "H&R": {
                        "include_all_tags": ["~H&R"],
                        "max_seeding_time": -1,
                        "max_ratio": -1
                    },
                    "dead_xseed": {
                        "include_all_tags": ["xs", "~noHL"],
                        "exclude_any_tags": ["ATH", "BLU", "BHD", "LST"],
                        "max_seeding_time": "5d"
                    },
                    "noHL": {
                        "include_all_tags": ["~noHL"],
                        "max_seeding_time": "90d"
                    },
                    "default": {
                        "max_seeding_time": -2,
                        "max_ratio": -2,
                        "add_group_to_tag": False
                    }
                }
            },
        },
        "tracker_details": {
            "myanonamouse": {
                "tag": "MAM",
                "HR": {
                    "time": "3d"
                },
                "category": "ebooks"
            },
            "aither": {
                "tag": "ATH",
                "HR": {
                    "time": "5d",
                    "percent": 20
                }
            },
            "blutopia": {
                "tag": "BLU",
                "HR": {
                    "time": "7d",
                    "percent": 10
                }
            },
            "torrentleech|tleechreload": {
                "tag": "TL",
                "HR": {
                    "time": "7d",
                    "ratio": 1,
                    "percent": 10
                }
            },
            "fearnopeer": {
                "tag": "FNP"
            },
            "f1carreras": {
                "tag": "F1C",
                "HR": {
                    "time": "2d"
                }
            },
               "avistaz": {
                "tag": "aZ",
                "HR": {
                    "time": "7d",
                    "ratio": 0.9,
                    "percent": 10
                }
            },
            "speedapp": {
                "tag": "SPD",
                "HR": {
                    "time": "48h",
                    "ratio": 1
                }
            },
            "filelist|thefl": {
                "tag": "FL",
                "HR": {
                    "time": "2d",
                    "ratio": 1
                }
            },
            "torrenteros": {
                "tag": "TTR",
                "HR": {
                    "time": "3d"
                }
            },
            "sportscult": {
                "tag": "SC",
                "HR": {
                    "time": "7d",
                    "ratio": 1
                }
            },
            "hd-olimpo": {
                "tag": "HDO",
                "HR": {
                    "time": "3d",
                    "percent": 15
                }
            },
            "torrentland": {
                "tag": "TLand",
                "HR": {
                    "time": "96h",
                    "percent": 10
                }
            },
            "hd-space": {
                "tag": "HDS",
                "HR": {
                    "time": "2d"
                }
            },
            "xbytes": {
                "tag": "XB",
                "HR": {
                    "time": "3d",
                    "percent": 50
                }
            },
            "hdzero": {
                "tag": "HDZ",
                "HR": {
                    "time": "5d",
                    "percent": 10
                }
            },
            "digitalcore": {
                "tag": "DC",
                "HR": {
                    "time": "5d",
                    "ratio": 1,
                    "percent": 10
                }
            },
            "seedpool": {
                "tag": "SP",
                "HR": {
                    "time": "10d",
                    "percent": 10
                }
            },
            "opsfet.ch": {
                "tag": "OPS"
            },
            "reelflix": {
                "tag": "RFLX"
            },
            "divteam": {
                "tag": "DivT"
            },
            "hawke": {
                "tag": "HUNO",
                "HR": {
                    "time": "5d",
                    "percent": 10
                }
            },
            "lst": {
                "tag": "LST",
                "HR": {
                    "time": "3d",
                    "percent": 10
                }
            },
            "beyond-hd": {
                "tag": "BHD",
                "HR": {
                    "time": "5d",
                    "ratio": 1,
                    "percent": 30
                }
            },
            "default": {
                "tag": "other"
            }
        }
    }

    @classmethod
    def set(cls, config):
        cls._config = config

    @classmethod
    def _get_from_dict(cls, source, path, default=None):
        parts = path.split('.')
        current = source
        for part in parts:
            if current is None:
                return default
            # Intentamos acceder como dict o atributo
            if isinstance(current, dict):
                current = current.get(part, None)
            else:
                current = getattr(current, part, None)
            if current is None:
                return default
        return current

    @classmethod
    def get(cls, path=None, default=None):
        """
        Busca primero en _config y si no encuentra, en DEFAULTS.
        Si no encuentra en ninguna, devuelve default.
        """
        def _get_from(source, path_parts):
            current = source
            for part in path_parts:
                if current is None:
                    return None
                if hasattr(current, part):
                    current = getattr(current, part)
                elif isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None
            return current

        if path is None:
            return cls._config or cls.DEFAULTS

        parts = path.split('.')

        # Primero intento en la config personalizada
        if cls._config is not None:
            result = _get_from(cls._config, parts)
            if result is not None:
                return result

        # Si no está, intento en DEFAULTS
        result = _get_from(cls.DEFAULTS, parts)
        if result is not None:
            # logger.warning(f"Using DEFAULT value for {path} key config. Value: {result}")
            return result

        # logger.warning(f"Config value for {path} key config not found. Using: {default}")

        # Si no está en ninguno, devuelvo param default
        return default


class Config:
    def __init__(self, yaml_path=None, config_dict=None, is_root=True):
        if is_root:
            if yaml_path is None:
                raise ValueError("Se debe proporcionar la ruta al fichero YAML")
            with open(yaml_path, "r", encoding="utf-8") as f:
                config_dict = yaml.safe_load(f)

        for key, value in config_dict.items():
            if isinstance(value, dict):
                value = Config(config_dict=value, is_root=False)
            elif isinstance(value, list):
                value = [
                    Config(config_dict=item, is_root=False) if isinstance(item, dict) else item
                    for item in value
                ]
            setattr(self, key, value)

        if not is_root:
            return

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __contains__(self, key):
        return hasattr(self, key)

    def keys(self):
        return self.__dict__.keys()

    def values(self):
        return self.__dict__.values()

    def items(self):
        return self.__dict__.items()

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __len__(self):
        return len(self.__dict__)

    def __iter__(self):
        return iter(self.__dict__)
