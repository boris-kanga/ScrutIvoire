# ScrutIvoire


```commandline

 hypercorn --reload --bind 0.0.0.0:5005 --access-logfile - --error-logfile - "src.web.views:create_app()"

```