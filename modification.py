import dataclasses
import datetime
from typing import List, Set, Tuple, Optional, Any
import subprocess
import re
import sys
import logging

_date_line = re.compile(r'^Date:\s*([0-9\-]+T[0-9\:]+)')

@dataclasses.dataclass()
class Modification:
    file_name: str
    javadoc_modification: str
    functionheader_modification: str
    functionheader_date: datetime
    time_offset: datetime

def escape(l: str):
    new_l=l.replace('[', '\[')
    new_l=new_l.replace(']', '\]')
    new_l=new_l.replace('/', '\/')
    new_l=new_l.replace('*', '\*')
    return new_l

def find_modification_before(file_name: str, pattern : str, lines_numbers: int, sha: str, before: datetime) -> datetime:
    str_lines = '-L/' + escape(pattern)+'/,+' + str(lines_numbers) +':' + file_name
    try:
        git_cmd = [
            'git', 'log', sha, '--date=iso-strict', str_lines
            ]
        log = subprocess.check_output(git_cmd).decode(sys.getdefaultencoding())
        log = log.replace('\r', '')
        loglines = log.split('\n')
        cur_date = None
        cur_realdatetime = None

        for l in loglines:
            cld = _date_line.match(l)
            if cld:
                cur_date = cld.group(1)
                cur_realdatetime = datetime.datetime.strptime(cur_date, "%Y-%m-%dT%H:%M:%S")
                if cur_realdatetime < before:
                    return cur_realdatetime
    except Exception as e:
        logging.warning(str(e))
        cur_realdatetime = None
    return cur_realdatetime
