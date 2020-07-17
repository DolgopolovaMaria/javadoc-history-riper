#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import shutil
import os
from typing import List, Set, Tuple, Optional, Any
import dataclasses
import enum
import pandas as pd
import openpyxl
from openpyxl.chart import DoughnutChart, Reference


import logging
import chardet
import tqdm
import subprocess
import re
import sys
import tempfile
import argparse
import csv
import itertools
import datetime

# git log --name-status --all
# git format-patch -1 --numbered-files --unified=100000 8aad90891ea4ab5762420c7424db7b01ec50c107 -- "bundles/org.eclipse.swt/Eclipse SWT PI/common_j2se/org/eclipse/swt/internal/Library.java"


_commit_line = re.compile(r'^commit ([0-9a-f]{40})$')
_date_line = re.compile(r'^Date:\s*([0-9\-]+T[0-9\:]+)')
_src_line = re.compile(r'^M\t((.+)\.java)$')
_javadoc_start_marker = re.compile(r'^((\+|\-)( |\t))?\s*/\*\*\s*')
_javadoc_end_marker = re.compile(r'^.*(\*/|\*\s*\*/)\s*$')
_javadoc_section_marker = re.compile(r'^((\+|\-)( |\t))?\s*(\*|/\*\*)?\s*@(param|return|exception|throw|throws)\s+')

_patch_plus_prefix = re.compile(r'^\+( |\t)')
_patch_minus_prefix = re.compile(r'^\-( |\t)')
_patch_plus_minus_prefix = re.compile(r'^(\+|\-)( |\t)?')
_patch_plus_minus_asterisk_prefix = re.compile(r'^(\+|\-)( |\t)*\*\s*$')
_function_headers = re.compile(r'^\s*(@\w+)*\s*(\w|\s|\[|\]|<|>|\?|,|\.|(\/\*\w+\*\/))+\((\w|\s|,|\.|\[|\]|<|>|\?|(\/\*\w+\*\/))*\)(\w|\s|,)*(\{|\;)')
whitespaces = re.compile(r'(\s)+')
_empty_line = re.compile(r'^(\+|\-)?( |\t)*\s*$')

_total_commits: int = 0
_java_files_commits: int = 0

def only_whitespaces(deleted: str, added: str) -> bool:
    deleted_without_whitspaces = whitespaces.sub('', deleted)
    added_without_whitespaces = whitespaces.sub('', added)
    return deleted_without_whitspaces == added_without_whitespaces

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

def find_commit_before(file_name: str, pattern : str, lines_numbers: int, sha: str, before: datetime) -> datetime:
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

# @numba.jit()
def has_java_javadoc_changed(file_name: str, patch: str, commit_date: datetime, sha: str, linecontext: int = 3) -> Tuple[bool, bool, bool, List[Modification]]:
    patchlines = patch.replace('\r', '').split('\n')

    has_javadoc_tag_changed = False
    has_javadoc_changed = False
    has_java_changed = False

    javadoc_lines_before = ''
    javadoc_lines_after = ''
    tag_lines_before = ''
    tag_lines_after = ''

    #interesting_line_indices: List[bool] = [False] * len(patchlines)

    modifications_in_file: List[Modification] = []
    javadoc_mod = ''
    functionheader_mod = ''

    going = False
    in_javadoc = False
    in_javadoc_tag_section = False
    in_javadoc_end = False
    tag_line = False
    lookfor_code = False
    lookfor_first_codeline = False
    lookfor_endtag = False
    linecode_list = []
    linedoc_list = []
    start_header = ''
    for l, ln in zip(patchlines, itertools.count()):
        in_javadoc_end = False
        tag_line = False
        if (lookfor_first_codeline and not _empty_line.match(l)) or lookfor_code:
            if lookfor_first_codeline:
                start_header = l.lstrip()
                lookfor_first_codeline = False
                lookfor_code = True
            linecode_list.append(l)  
            lines_ = "".join(linecode_list)
            match = _function_headers.search(lines_)
            if match:
                lookfor_code = False
                lookfor_first_codeline = False
                number_of_lines = len(linecode_list)
                functionheader_mod = '\n'.join(k for k in linecode_list)
                javadoc_mod = '\n'.join(k for k in linedoc_list)
                linecode_list = []
                linedoc_list = []
                commit_before = find_commit_before(file_name, start_header, number_of_lines, sha,  commit_date)
                offset = commit_date-commit_before
                modifications_in_file.append(Modification(file_name, javadoc_mod, functionheader_mod, commit_before, offset))
            elif len(linecode_list) > 9:
                lookfor_code = False
                lookfor_first_codeline = False
                javadoc_mod = '\n'.join(k for k in linedoc_list)
                linecode_list = []
                linedoc_list = []
                modifications_in_file.append(Modification(file_name, javadoc_mod, None, None, None))
        if l.startswith('@@'):
            going = True
        elif l.startswith('--'):
            going = False
        elif going and not in_javadoc and _javadoc_start_marker.match(l):
            in_javadoc = True
        if going and in_javadoc and not in_javadoc_tag_section and _javadoc_section_marker.match(l):
            tag_line = True
            in_javadoc_tag_section = True
            lookfor_code = False
            lookfor_endtag = False
            linecode_list = []
            linedoc_list = []
        if going and in_javadoc and _javadoc_end_marker.match(l):
            in_javadoc = False
            in_javadoc_tag_section = False
            in_javadoc_end = True
            if lookfor_endtag:
                lookfor_endtag = False
                lookfor_first_codeline = True
                linecode_list = []
        if going and _patch_plus_minus_prefix.match(l):
            if _patch_plus_minus_asterisk_prefix.match(l):
                continue
            if in_javadoc_tag_section or in_javadoc_end:
                if in_javadoc_tag_section or in_javadoc_end and tag_line:
                    has_javadoc_tag_changed = True
                    # interesting_line_indices[ln] = True
                    linedoc_list.append(l)
                    #for zi in range(max(0, ln - linecontext), min(len(patchlines), ln + linecontext) + 1):
                    #    interesting_line_indices[zi] = True
                if _patch_minus_prefix.match(l):
                    tag_lines_before = tag_lines_before + l[2:]
                elif _patch_plus_prefix.match(l):
                    tag_lines_after = tag_lines_after + l[2:]
                if in_javadoc_tag_section:
                    lookfor_endtag = True
                elif tag_line:
                    lookfor_first_codeline = True
                    linecode_list = []
            elif in_javadoc:
                has_javadoc_changed = True
                if _patch_minus_prefix.match(l):
                    javadoc_lines_before = javadoc_lines_before + l[2:]
                elif _patch_plus_prefix.match(l):
                    javadoc_lines_after = javadoc_lines_after + l[2:]
            else:
                has_java_changed = True
                lookfor_code = False
                lookfor_first_codeline = False
                linecode_list = []
                linedoc_list = []
        else:
            if in_javadoc_tag_section:
                tag_lines_before = tag_lines_before + l[2:]
                tag_lines_after = tag_lines_after + l[2:]
            elif in_javadoc:
                javadoc_lines_before = javadoc_lines_before + l[2:]
                javadoc_lines_after = javadoc_lines_after + l[2:]

    if only_whitespaces(javadoc_lines_before, javadoc_lines_after):
        has_javadoc_changed = False
    if only_whitespaces(tag_lines_before, tag_lines_after):
        has_javadoc_tag_changed = False
        
    #if has_javadoc_tag_changed and not has_java_changed:
    #    brief = '\n'.join(
    #        l for l, n in zip(patchlines, interesting_line_indices) if n
    #    )
    #else:
    #    brief = ""
    
    return has_java_changed, has_javadoc_changed, has_javadoc_tag_changed, modifications_in_file

@enum.unique
class CommitType(enum.Enum):
    UNKNOWN = None
    JAVA_AND_JAVADOC_TAGS_EVERYWHERE = "Arbitrary Java / JavaDoc changes"
    ONLY_JAVADOC_TAGS_IN_SOME_FILES = "Some files have only JavaDoc tag changes"
    ONLY_JAVADOC_TAGS_EVERYWHERE = "Whole commit has only JavaDoc tag changes"
    WITHOUT_JAVADOC_TAGS = "Commit doesn't have JavaDoc tag changes"

_mixed_commits: int = 0
_only_javadoc_in_some_files_commits: int = 0
_pure_javadoc_commits: int = 0

@dataclasses.dataclass()
class Commit:
    sha1: str
    files: List[Optional[str]] = None
    date: datetime = None
    commit_type: CommitType = CommitType.UNKNOWN
    file_statuses: List[Tuple[bool, bool, bool]] = None
    modifications: List[Modification] = None

    @staticmethod
    def read_file_in_any_encoding(patch_filename: str, filename: str, comment: str = "") -> str:
        with open(patch_filename, 'rb') as bf:
            bts = bf.read()
        try:
            return bts.decode('utf-8')
        except Exception as ude1:
            logging.warning(f"File: {filename} of {comment} is not in UTF-8: {ude1}")
            try:
                return bts.decode(sys.getdefaultencoding())
            except Exception as ude2:
                logging.warning(f"File: {filename} of {comment} is not in sys.getdefaultencoding() = {sys.getdefaultencoding()}: {ude2}")
                # Can't handle more here...
                enc = chardet.detect(bts)['encoding']
                logging.warning(f"File: {filename} of {comment} is likely in {enc} encoding")
                return bts.decode(enc)

    def classify(self, tmpdir):
        global _mixed_commits, _only_javadoc_in_some_files_commits, _pure_javadoc_commits

        file_statuses: List[Tuple[bool, bool, bool]] = []
        modifications: List[Modification] = []

        for f in self.files:
            patchname = subprocess.check_output([
                'git', 'format-patch', '-1', '--numbered-files', '--unified=100000',
                '-o', tmpdir, self.sha1,
                '--', f
            ]).decode(sys.getdefaultencoding()).strip()
            try:
                patch = self.read_file_in_any_encoding(patchname, f, f"Commit: {self.sha1}")
                tuple_ = has_java_javadoc_changed(f, patch, self.date, self.sha1)
                file_statuses.append((tuple_[0], tuple_[1], tuple_[2]))
                if tuple_[2] and not tuple_[0] and not  tuple_[1]:
                    modifications.extend(tuple_[3])
            except Exception as e:
                logging.error("Skipping bad patch of commit %s in file %s due to %s" % (self.sha1, f, e))
                file_statuses.append((False, False, False))

        pure_javadoc_tag_files_count = sum(
            1 for (j, d, t) in file_statuses if t and not j and not d
        )

        javadoc_tag_files_count = sum(
            1 for (j, d, t) in file_statuses if t
        )

        if pure_javadoc_tag_files_count == len(file_statuses):
            self.commit_type = CommitType.ONLY_JAVADOC_TAGS_EVERYWHERE
            _pure_javadoc_commits += 1
        elif pure_javadoc_tag_files_count > 0:
            self.commit_type = CommitType.ONLY_JAVADOC_TAGS_IN_SOME_FILES
            _only_javadoc_in_some_files_commits += 1
        elif javadoc_tag_files_count == 0:
            self.commit_type = CommitType.WITHOUT_JAVADOC_TAGS
        else:
            self.commit_type = CommitType.JAVA_AND_JAVADOC_TAGS_EVERYWHERE
            _mixed_commits += 1

        self.file_statuses = file_statuses
        self.modifications = modifications


    # def get_file_statuses_str(self) -> str:
    #     res = []
    #     for f, (j, d, t, s) in zip(self.files, self.file_statuses):
    #         if len(s):
    #             res.append("%s:\n%s\n" % (f, s))
    #     return "\n".join(res)

    def get_csv_lines(self, url_prefix: str) -> List[List[str]]:
        if not self.modifications:
            return [[self.commit_type.value, url_prefix + self.sha1, self.date, '', '', '']]
        csv_lines = []
        for i in range(0, len(self.modifications)):
            csv_lines.append(self.csv_line(i, url_prefix))
        return csv_lines

    def csv_line(self, i: int, url_prefix: str) -> List[str]:
        if i < 1:
            if self.modifications[0].time_offset is None:
                return [
                    self.commit_type.value, 
                    url_prefix + self.sha1, 
                    self.date, 
                    self.modifications[0].file_name, 
                    self.modifications[0].javadoc_modification, 
                    self.modifications[0].functionheader_modification, 
                    self.modifications[0].functionheader_date, 
                    '', 
                    ''
                    ]
            else:
                return [
                    self.commit_type.value, 
                    url_prefix + self.sha1, 
                    self.date, 
                    self.modifications[0].file_name, 
                    self.modifications[0].javadoc_modification, 
                    self.modifications[0].functionheader_modification, 
                    self.modifications[0].functionheader_date, 
                    self.modifications[0].time_offset.days, 
                    self.modifications[0].time_offset.seconds//3600+self.modifications[0].time_offset.days*24
                    ]
        else:
            if self.modifications[i].time_offset is None:
                return [
                    '', 
                    '', 
                    '', 
                    self.modifications[i].file_name, 
                    self.modifications[i].javadoc_modification, 
                    self.modifications[i].functionheader_modification, 
                    self.modifications[i].functionheader_date, 
                    '', 
                    ''
                    ]
            else:
                return [
                    '', 
                    '', 
                    '', 
                    self.modifications[i].file_name, 
                    self.modifications[i].javadoc_modification, 
                    self.modifications[i].functionheader_modification, 
                    self.modifications[i].functionheader_date, 
                    self.modifications[i].time_offset.days, 
                    self.modifications[i].time_offset.seconds//3600+self.modifications[i].time_offset.days*24
                    ]


def get_commits(single_commit: Optional[str] = None) -> List[Commit]:
    global _total_commits

    git_cmd = [
        'git', 'show', '--name-status', '--date=iso-strict', single_commit
    ] if single_commit else [
        'git', 'log', '--name-status', '--date=iso-strict', '--all'
    ]

    log = subprocess.check_output(git_cmd).decode(sys.getdefaultencoding())
    log = log.replace('\r', '')
    loglines = log.split('\n')
    commits = []
    cur_commit = None
    cur_date = None
    cur_files = []

    def release():
        global _java_files_commits
        if cur_commit and len(cur_files):
            _java_files_commits += 1
            cur_realdatetime = datetime.datetime.strptime(cur_date, "%Y-%m-%dT%H:%M:%S")
            commits.append(Commit(cur_commit, cur_files.copy(), cur_realdatetime))

    print("Analyzing log...")

    for l in tqdm.tqdm(loglines):
        clm = _commit_line.match(l)
        clf = _src_line   .match(l)
        cld = _date_line.match(l)
        if clm:
            _total_commits += 1
            release()
            cur_commit = clm.group(1)
            cur_files = []
        elif cld:
            cur_date = cld.group(1)
        elif clf:
            cur_files.append(clf.group(1))
    release()
    return commits

def statistics_to_excel():
    df = pd.DataFrame([
        ["Commits with Java file changes", _java_files_commits],
        ["Commits having JavaDoc tags changed", _mixed_commits + _only_javadoc_in_some_files_commits + _pure_javadoc_commits],
        ["Commits having Code and JavaDoc tags changed in all files", _mixed_commits],
        ["Commits having files with only JavaDoc tag changes", _only_javadoc_in_some_files_commits],
        ["Commits exclusively of JavaDoc tag changes", _pure_javadoc_commits]
    ])
    with pd.ExcelWriter('__statistics.xlsx', engine='openpyxl') as writer:
        df.to_excel(writer, 'Statistics', index_label=False, index=False, header=False)
    wb = openpyxl.load_workbook('__statistics.xlsx')        
    worksheet = wb.active
    col = worksheet['A']
    max_length = 0
    for cell in col:
        try:
            if len(str(cell.value)) > max_length:
                max_length = len(cell.value)
        except Exception as e:
            logging.warning(str(e))
            continue
    adjusted_width = (max_length + 2) * 1.2
    worksheet.column_dimensions['A'].width = adjusted_width

    chart = DoughnutChart()
    chart.type = "filled"
    labels = Reference(worksheet, min_col = 1, min_row = 3, max_row = 5)
    data = Reference(worksheet, min_col = 2, min_row = 3, max_row = 5)
    chart.add_data(data, titles_from_data = False)
    chart.set_categories(labels)
    chart.title = "Commits Chart"
    chart.style = 26
    worksheet.add_chart(chart, "C7")
    
    wb.save('__statistics.xlsx')


def calc_stats(args: argparse.Namespace):
    commits = get_commits(
        args.only_commit if 'only_commit' in args else None
    )

    print("Analyzing commits...")

    try:
        tmpdir = tempfile.mkdtemp()
        for c in tqdm.tqdm(commits):
            c.classify(tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    commit_lines = []
    for c in commits:
        if c.commit_type in {CommitType.ONLY_JAVADOC_TAGS_EVERYWHERE, CommitType.ONLY_JAVADOC_TAGS_IN_SOME_FILES}:
            commit_lines.extend(c.get_csv_lines(args.commit_prefix))

    df = pd.DataFrame(commit_lines)
    with pd.ExcelWriter('__commits.xlsx', engine='openpyxl') as writer:
        df.to_excel(writer, 'Commits', index_label=False, index=False, header=False)

    statistics_to_excel()

    print("Report")
    print("======")
    print("Total commits:", _total_commits)
    print("Commits with Java file changes:", _java_files_commits)
    print("Commits having Code and JavaDoc tags changed in all files: ", _mixed_commits)
    print("Commits having files with only JavaDoc tag changes:", _only_javadoc_in_some_files_commits)
    print("Commits exclusively of JavaDoc tag changes:", _pure_javadoc_commits)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(logging.FileHandler('__rip-rep-logs.log'))

    argparser = argparse.ArgumentParser()
    argparser.add_argument('-cp', '--commit-prefix', type=str, default="https://github.com/albertogoffi/toradocu/commit/")
    #argparser.add_argument('-cl', '--context-lines', type=int, default=3)
    argparser.add_argument('-oc', '--only-commit', type=str, required=False, help=\
        "For debug purposes. Only analyse given commit, e.g. 7051049221c9d3b99ff179f167fa09a6e02138ee")
    args = argparser.parse_args()
    calc_stats(args)
