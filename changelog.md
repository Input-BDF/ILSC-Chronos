# Chronos changelog

## 2026-08-xx - v0.3.0

- refactor
    - split `CalendarHandler` into classes `BaseCalendarHandler`, `IcsCalendarHandler` and `CalDavCalendarHandler`
    - split `ChronosEvent` into classes `BaseChronosEvent`, `IcsChronosEvent` and `CalDavChronosEvent`
    - move functionality from `CalDavChronosEvent` to `CalendarHandler`
        - saving, sanitizing, updating
    - move functionality from `AppFactory` to `CalendarHandler`
        - syncing
- `BaseChronosEvent.sanitize_description`: fix handling special characters

## 2026-03-03 - v0.2.0

- add reading from ICS calendars

## 2024-08-20 - v0.1.0

- initial release
