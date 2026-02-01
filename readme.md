# Chronos

Chronos is the central service for combining the single (event planning) calendars into one (public readable) calendar. The last can be the central information base for multiple endpoints. In the same operation minor cleanups and "beauty" operations are performed to visualize events within the source calendars a little bit better.

## Main Features:
  * synchronize CalDav based calendar events
  * N:1 calendar synchronisation
    
## Setup

As chronos runs in background it should run as dedicated user. We will create an according home directory under ''/opt/chronos''
```
$ adduser chronos --system --home /opt/chronos --group
```

Clone repository into ```/opt/chronos```

```
# start user session with shell (as system user has no shell assigned)
$ sudo su - chronos -s /bin/bash
$ whoami
$ git clone https://github.com/Input-BDF/ILSC-Chronos.git
# Change permissions to 750 as passwords are stored inside config files
$ chmod -R 750 ~/ILSC-Chronos
```

Prepare pipenv environment
```
$ cd /opt/chronos/ILSC-Chronos
$ pipenv install
```

Adjust service configuration file
```
$ cd /opt/chronos/ILSC-Chronos/src/config/
$ cp app.cfg_default app.cfg
$ nano app.cfg
```

```
[app]
#Cron running to check for updates run full data-collector every day at 0000h
datacron = 1-59/10
#run gspread and caldav parser every n-th hour of day
appcron = 4
timezone = Europe/Berlin
app_id = Chronos

[calendars]
path = /opt/chronos/ILSC-Chronos/src/config
filename = calendars.json
range_min = 0
range_max = 365
prefix_format = $icons $prefix
delete_on_target = True

[log]
path = /opt/chronos/ILSC-Chronos/src/logs
filename = application.log
#predefined levels (CRITICAL, ERROR, WARNING, INFO, DEBUG)
#using DEBUG will create an additional [file]_debug log
level = INFO
# second (s) minute (m) hour (h) day (d) w0-w6 (weekday, 0=Monday) midnight
rotation = d
# interval of rotation
interval = 1
# kept backup files
backups = 7
```

Adjust calendar configuration file
```
$ cd /opt/chronos/ILSC-Chronos/src/config/
$ cp calendars.json_default calendars.json
$ nano calendars.json
```

```
{
        "calendars" : [
                {
                        "cal_primary" : "https://example.com/remote.php/dav",
                        "cal_name" : "CalendarName",
                        "cal_user" : "UserName",
                        "cal_passwd" : "PassWD",
                        "time_zone" : "Europe/Berlin",
                        "force_time" : true,
                        "force_start" : "21:00",
                        "force_end" : "23:59",
                        "ignore_planned" : true,
                        "ignore_descriptions": false,
                        "title_prefix" : "BD CLUB",
                        "tags" : ["BD","ILSC"],
                        "tags_excluded": [
                                "Intern",
                                "Ignore",
                                "Nutzung"
                        ],
                        "color" : "lightskyblue",
                        "default_location" : "BD CLUB",
                        "sanitize" : {
                                "stati" : true,
                                "source_icons" : true,
                                "target_icons" : true
                        }
                },
                {
                        "cal_primary" : "https://example.com/remote.php/dav",
                        "cal_name" : "CalendarName",
                        "cal_user" : "UserName",
                        "cal_passwd" : "PassWD",
                        "time_zone" : "Europe/Berlin",
                        "force_time" : true,
                        "force_start" : "21:00",
                        "force_end" : "23:59",
                        "ignore_planned" : true,
                        "ignore_descriptions": false,
                        "title_prefix" : "BD CLUB",
                        "tags" : ["BD","ILSC"],
                        "tags_excluded": [
                                "Intern",
                                "Ignore",
                                "Nutzung"
                        ],
                        "color" : "lightskyblue",
                        "default_location" : "BD CLUB",
                        "sanitize" : {
                                "stati" : true,
                                "source_icons" : true,
                                "target_icons" : true
                        }
                },
        ],
        "target" : {
                "cal_primary" : "https://example.com/remote.php/dav",
                "cal_name" : "CalendarName",
                "cal_user" : "UserName",
                "cal_passwd" : "PassWD",
                "time_zone" : "Europe/Berlin"
        },
        "icons_non_encode" : {
        "Band" : "🎸",
        "DJ" : "🎧",
        "Lesung" : "📖",
        "Special" : "✨",
        "Meeting" : "📅",
        "Treffen" : "📅"
        },
        "icons" : {
                "Band": "\ud83c\udfb8",
                "DJ": "\ud83c\udfa7",
                "Lesung": "\ud83d\udcd6",
                "Special": "\u2728",
                "Meeting": "\ud83d\udcc5",
                "Treffen": "\ud83d\udcc5"
        }
}
```

Create systemd unit file
```
$ nano /etc/systemd/system/ilsc-chronos.service
```

```
[Unit]
Description=ILSC Chronos Service
After=network.target

[Service]
User=chronos
Group=chronos
Type=simple
#PIDFile=/opt/chronos/ilsc-chronos.pid
Restart=always
RestartSec=5
WorkingDirectory=/opt/chronos/ILSC-Chronos/src/
ExecStart=/usr/bin/pipenv run python3 /opt/chronos/ILSC-Chronos/src/app.py
ExecReload=/bin/kill -s HUP $MAINPID
ExecStop=/bin/kill -s QUIT $MAINPID
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Reload systemd, run service and check status

```
$ systemctl daemon-reload
$ systemctl start ilsc-chronos.service
$ systemctl status ilsc-chronos.service
```

Finaly enable service file tu run at boot

```
$ systemctl enable ilsc-chronos.service
```

## Check the logs
To find out what's going on check ''journalctl'' or the current logfile. The service itself has log rotation on the wheels. Check app.cfg.

```
$ sudo journalctl -f -u ilsc-chronos
$ sudo tail -f /opt/chronos/ILSC-Chronos/src/logs/application.log
```

## Tested with Nextcloud and Baikal calendars

* Shared calendar (login required)
* via Private link (login required)
* Public link (readonly, remove ?export parameter)

* For Nextcloud best practice is to use App-Passwords (else session overview will be really spammed)
