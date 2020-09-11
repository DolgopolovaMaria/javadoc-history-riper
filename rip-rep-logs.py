#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import shutil
import os
from typing import List, Set, Tuple, Optional, Any
import dataclasses
import pandas as pd
import openpyxl
from openpyxl.chart import DoughnutChart, Reference
import logging
import tqdm
import tempfile
import argparse
import csv
import commits
from commits import Commit, CommitType, get_commits

# git log --name-status --all
# git format-patch -1 --numbered-files --unified=100000 8aad90891ea4ab5762420c7424db7b01ec50c107 -- "bundles/org.eclipse.swt/Eclipse SWT PI/common_j2se/org/eclipse/swt/internal/Library.java"


def statistics_to_excel():
    df = pd.DataFrame([
        ["Commits with Java file changes", commits._java_files_commits],
        ["Commits having JavaDoc tags changed", commits._mixed_commits + commits._only_javadoc_in_some_files_commits + commits._pure_javadoc_commits],
        ["Commits having Code and JavaDoc tags changed in all files", commits._mixed_commits],
        ["Commits having files with only JavaDoc tag changes", commits._only_javadoc_in_some_files_commits],
        ["Commits exclusively of JavaDoc tag changes", commits._pure_javadoc_commits]
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
    commits_list = get_commits(
        args.only_commit if 'only_commit' in args else None
    )

    print("Analyzing commits...")

    try:
        tmpdir = tempfile.mkdtemp()
        for c in tqdm.tqdm(commits_list):
            c.classify(tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    commit_lines = []
    for c in commits_list:
        if c.commit_type in {CommitType.ONLY_JAVADOC_TAGS_EVERYWHERE, CommitType.ONLY_JAVADOC_TAGS_IN_SOME_FILES}:
            commit_lines.extend(c.get_csv_lines(args.commit_prefix))

    df = pd.DataFrame(commit_lines)
    with pd.ExcelWriter('__commits.xlsx', engine='openpyxl') as writer:
        df.to_excel(writer, 'Commits', index_label=False, index=False, header=False)

    statistics_to_excel()

    print("Report")
    print("======")
    print("Total commits:", commits._total_commits)
    print("Commits with Java file changes:", commits._java_files_commits)
    print("Commits having Code and JavaDoc tags changed in all files: ", commits._mixed_commits)
    print("Commits having files with only JavaDoc tag changes:", commits._only_javadoc_in_some_files_commits)
    print("Commits exclusively of JavaDoc tag changes:", commits._pure_javadoc_commits)


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
