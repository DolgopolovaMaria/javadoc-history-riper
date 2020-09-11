from typing import List, Set, Tuple, Optional, Any
import re
import logging
import datetime
import itertools
from modification import Modification, find_modification_before


_javadoc_start_marker = re.compile(r'^((\+|\-)( |\t))?\s*/\*\*\s*')
_javadoc_end_marker = re.compile(r'^.*(\*/|\*\s*\*/)\s*$')
_javadoc_section_marker = re.compile(r'^((\+|\-)( |\t))?\s*(\*|/\*\*)?\s*@(param|return|exception|throw|throws)\s+')
_javadoc_uninteresting_tags = re.compile(r'^((\+|\-)( |\t))?\s*(\*|/\*\*)?\s*@(author|deprecated|see|since|version|serial)\s+')

_patch_plus_prefix = re.compile(r'^\+( |\t)')
_patch_minus_prefix = re.compile(r'^\-( |\t)')
_patch_plus_minus_prefix = re.compile(r'^(\+|\-)( |\t)?')
_patch_plus_minus_asterisk_prefix = re.compile(r'^(\+|\-)( |\t)*\*\s*$')
_function_headers = re.compile(r'^\s*(@\w+)*\s*(\w|\s|\[|\]|<|>|\?|,|\.|(\/\*\w+\*\/))+\((\w|\s|,|\.|\[|\]|<|>|\?|(\/\*\w+\*\/))*\)(\w|\s|,)*(\{|\;)')
whitespaces = re.compile(r'(\s)+')
_empty_line = re.compile(r'^(\+|\-)?( |\t)*\s*$')

def only_whitespaces(deleted: str, added: str) -> bool:
    deleted_without_whitspaces = whitespaces.sub('', deleted)
    added_without_whitespaces = whitespaces.sub('', added)
    return deleted_without_whitspaces == added_without_whitespaces

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
                modification_before = find_modification_before(file_name, start_header, number_of_lines, sha,  commit_date)
                offset = commit_date-modification_before
                modifications_in_file.append(Modification(file_name, javadoc_mod, functionheader_mod, modification_before, offset))
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
        elif going and in_javadoc_tag_section and _javadoc_uninteresting_tags.match(l):
            in_javadoc_tag_section = False
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