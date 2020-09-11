
import datetime
import enum
import logging
import chardet
import tqdm
import subprocess
import re
import sys
import dataclasses
from typing import List, Set, Tuple, Optional, Any
from modification import Modification
from javadoc_analyzer import has_java_javadoc_changed


_commit_line = re.compile(r'^commit ([0-9a-f]{40})$')
_date_line = re.compile(r'^Date:\s*([0-9\-]+T[0-9\:]+)')
_src_line = re.compile(r'^M\t((.+)\.java)$')
    
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
_total_commits: int = 0
_java_files_commits: int = 0

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
            return [[self.commit_type.value, url_prefix + self.sha1, self.date, '', '']]
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
                    ''
                    ]
            return [
                self.commit_type.value, 
                url_prefix + self.sha1, 
                self.date, 
                self.modifications[0].file_name, 
                self.modifications[0].javadoc_modification, 
                self.modifications[0].functionheader_modification, 
                self.modifications[0].functionheader_date, 
                self.modifications[0].time_offset.days
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
                    ''
                    ]
            return [
                '', 
                '', 
                '', 
                self.modifications[i].file_name, 
                self.modifications[i].javadoc_modification, 
                self.modifications[i].functionheader_modification, 
                self.modifications[i].functionheader_date, 
                self.modifications[i].time_offset.days
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