# Copyright (C) 2010 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Service details and instances for the Docs service using GData 3.0.

Some use cases:
Upload a document:
  docs upload --folder "Some folder" path_to_doc

Edit a document in your word editor:
  docs edit --title "Grocery List" --editor vim (editor also set in prefs)

Download docs:
  docs get --folder "Some folder"

"""
from __future__ import with_statement

__author__ = 'tom.h.miller@gmail.com (Tom Miller)'
import ConfigParser
import logging
import os
import shlex
import shutil
import googlecl
from googlecl.docs import SECTION_HEADER

# Renamed here to reduce verbosity in other sections
safe_encode = googlecl.safe_encode
safe_decode = googlecl.safe_decode


LOG = logging.getLogger(googlecl.docs.LOGGER_NAME + '.base')


class DocsError(googlecl.base.Error):
  """Base error for Docs errors."""
  pass

class UnexpectedExtension(DocsError):
  """Found an unexpected filename extension."""
  def __str__(self):
    if len(self.args) == 1:
      return 'Unexpected extension: ' + str(self.args[0])
    else:
      return str(self.args)

class UnknownDoctype(DocsError):
  """Document type / label is unknown."""
  def __str__(self):
    if len(self.args) == 1:
      return 'Unknown document type: ' + str(self.args[0])
    else:
      return str(self.args)


class DocsBaseCL(object):

  """Class meant to be inherited by either DocsClientCL or DocsServiceCL."""

  # Marked with leading underscore because people should use the method
  # for creating folders appropriate to the superclass.
  def _create_folder(folder_name, folder_or_uri=None):
    raise NotImplementedError('_modify_entry must be defined!')

  def edit_doc(self, doc_entry_or_title, editor, file_ext,
               folder_entry_or_path=None):
    """Edit a document.

    Keyword arguments:
      doc_entry_or_title: DocEntry of the existing document to edit,
                          or title of the document to create.
      editor: Name of the editor to use. Should be executable from the user's
              working directory.
      file_ext: Suffix of the file to download.
                For example, "txt", "csv", "xcl".
      folder_entry_or_path: Entry or string representing folder to upload into.
                   If a string, a new set of folders will ALWAYS be created.
                   For example, 'my_folder' to upload to my_folder,
                   'foo/bar' to upload into subfolder bar under folder foo.
                   Default None for root folder.

    """
    import subprocess
    import tempfile

    try:
      doc_title = safe_decode(doc_entry_or_title.title.text)
      new_doc = False
    except AttributeError:
      doc_title = doc_entry_or_title
      new_doc = True

    temp_dir = tempfile.mkdtemp()
    # If we're creating a new document and not given a folder entry
    if new_doc and isinstance(folder_entry_or_path, basestring):
      folder_path = os.path.normpath(folder_entry_or_path)
      # Some systems allow more than one path separator
      if os.altsep:
        folder_path.replace(os.altsep, os.sep)
      base_folder = folder_path.split(os.sep)[0]
      # Define the base path such that upload_docs will create a folder
      # named base_folder
      base_path = os.path.join(temp_dir, base_folder)
      total_basename = os.path.join(temp_dir, folder_path)
      os.makedirs(total_basename)
      path = os.path.join(total_basename, doc_title + '.' + file_ext)
    else:
      path = os.path.join(temp_dir, doc_title + '.' + file_ext)
      base_path = path

    if not new_doc:
      self.Export(doc_entry_or_title.content.src, path)
      file_hash = _md5_hash_file(path)
    else:
      file_hash = None

    command_args = shlex.split(safe_encode(editor)) + [path]
    subprocess.call(command_args)
    impatient_editors = self.config.lazy_get(SECTION_HEADER,
                                             'impatient_editors',
                                             default='')
    if impatient_editors:
      impatient_editors = impatient_editors.split(',')
      if command_args[0] in impatient_editors:
        LOG.info('I noticed you are using an application that will not wait for '
                 'you to finish editing your file.')
        LOG.info('Hit enter in this shell when you finished editing and saved '
                 'your work.')
        raw_input('')
    if file_hash and file_hash == _md5_hash_file(path):
      LOG.info('No modifications to file, not uploading.')
      return
    elif not os.path.exists(path):
      LOG.info('No file written, not uploading.')
      return

    if new_doc:
      if isinstance(folder_entry_or_path, basestring):
        # Let code in upload_docs handle the creation of new folder(s)
        self.upload_docs([base_path])
      else:
        # folder_entry_or_path is None or a GDataEntry.
        self.upload_single_doc(path, folder_entry=folder_entry_or_path)
    else:
      try:
        self._modify_entry(doc_entry_or_title, path, file_ext)
      except self.request_error, err:
        LOG.error(err)
        new_path = safe_move(path, '.')
        LOG.info(safe_encode('Moved edited document to ' +
                             safe_decode(new_path)))

    try:
      # Good faith effort to keep the temp directory clean.
      shutil.rmtree(temp_dir)
    except OSError:
      # Only seen errors on Windows, but catch the more general OSError.
      pass

  EditDoc = edit_doc

  def get_docs(self, base_path, entries, file_ext=None):
    """Download documents.

    Keyword arguments:
      base_path: The path to download files to. This plus an entry's title plus
                 its format-specific extension will form the complete path.
      entries: List of DocEntry items representing the files to download.
      file_ext: Suffix to give the file(s) when downloading.
                For example, "txt", "csv", "xcl". Default None to let
                get_extension_from_doctype decide the extension. Ignored
                when downloading arbitrary files.

    """
    if not os.path.isdir(base_path):
      if len(entries) > 1:
        raise DocsError(safe_encode(u'Specified multiple source files, but ' +
                                    u'destination "' + base_path +
                                    u'" is not a directory'))
      format_from_filename = googlecl.get_extension_from_path(base_path)
      if format_from_filename and not file_ext:
        # Strip the extension off here if it exists. Don't want to double up
        # on extension in for loop. (+1 for '.')
        base_path = base_path[:-(len(format_from_filename)+1)]
        # We can just set the file_ext here, since there's only one file.
        file_ext = format_from_filename
    for entry in entries:
      # Don't set file_ext if we cannot do export.
      # get_extension_from_doctype will check the config file for 'format'
      # which will set an undesired entry_file_ext for
      # unconverted downloads
      if not file_ext and can_export(entry):
        entry_file_ext = get_extension_from_doctype(get_document_type(entry),
                                                    self.config)
      else:
        entry_file_ext = file_ext
      if entry_file_ext:
        LOG.debug('Decided file_ext is ' + entry_file_ext)
        extension = '.' + entry_file_ext
      else:
        LOG.debug('Could not (or would not) set file_ext')
        if can_export(entry):
          extension = '.txt'
        else:
          # Files that cannot be exported typically have a file extension
          # in their name / title.
          extension = ''

      entry_title = safe_decode(entry.title.text)
      if os.path.isdir(base_path):
        path = os.path.join(base_path, entry_title + extension)
      else:
        path = base_path + extension
      LOG.info(safe_encode('Downloading ' + entry_title + ' to ' + path))
      try:
        if can_export(entry):
          self.Export(entry, path)
        else:
          self.Download(entry, path)
      except self.request_error, err:
        LOG.error(safe_encode('Download of ' + entry_title + ' failed: ' +
                              unicode(err)))
      except EnvironmentError, err:
        LOG.error(err)
        LOG.info('Does your destination filename contain invalid characters?')

  GetDocs = get_docs

  def _modify_entry(doc_entry, path_to_new_content, file_ext):
    """Modify the file data associated with a document entry."""
    raise NotImplementedError('_modify_entry must be defined!')

  def upload_docs(self, paths, title=None, folder_entry=None,
                  file_ext=None, **kwargs):
    """Upload a list of documents or directories.

    For each item in paths:
      if item is a directory, upload all files found in the directory
        in a manner roughly equivalent to "cp -R directory/ <docs_folder>"
      if item is a file, upload that file to <docs_folder>

    Keyword arguments:
      paths: List of file paths and/or directories to upload.
      title: Title to give the files once uploaded.
             Default None for the names of the files.
      folder_entry: GDataEntry of the folder to treat as the new root for
                    directories/files.
                    Default None for no folder (the Google Docs root).
      file_ext: Replace (or specify) the extension on the file when figuring
              out the upload format. For example, 'txt' will upload the
              file as if it was plain text. Default None for the file's
              extension (which defaults to 'txt' if there is none).
      kwargs: Typically contains 'convert', indicates if we should convert the
              file on upload. False will only be honored if the user is a Google
              Apps Premier account.

    Returns:
      Dictionary mapping filenames to where they can be accessed online.

    """
    url_locs = {}
    for path in paths:
      folder_root = folder_entry
      if os.path.isdir(path):
        folder_entries = {}
        # final '/' sets folder_name to '' which causes
        # 503 "Service Unavailable".
        path = path.rstrip(os.path.sep)
        for dirpath, dirnames, filenames in os.walk(path):
          directory = os.path.dirname(dirpath)
          folder_name = os.path.basename(dirpath)
          if directory in folder_entries:
            fentry = self._create_folder(folder_name, folder_entries[directory])
          else:
            fentry = self._create_folder(folder_name, folder_root)
          folder_entries[dirpath] = fentry
          LOG.debug('Created folder ' + dirpath + ' ' + folder_name)
          for fname in filenames:
            loc = self.upload_single_doc(os.path.join(dirpath, fname),
                                         folder_entry=fentry)
            if loc:
              url_locs[fname] = loc
      else:
        loc = self.upload_single_doc(path, title=title,
                                     folder_entry=folder_entry,
                                     file_ext=file_ext,
                                     **kwargs)
        if loc:
          url_locs[os.path.basename(path)] = loc
    return url_locs

  UploadDocs = upload_docs

# Read size is 128*20 for no good reason.
# Just want to avoid reading in the whole file, and read in a multiple of 128.
def _md5_hash_file(path, read_size=2560):
  """Return a binary md5 checksum of file at path."""
  import hashlib
  hash_function = hashlib.md5()
  with open(path, 'r') as my_file:
    data = my_file.read(read_size)
    while data:
      hash_function.update(data)
      data = my_file.read(read_size)
  return hash_function.digest()


def can_export(entry_or_url):
  """See if the given entry can be exported.

  Based off check done in gdata.docs.client.DocsClient.export

  Returns:
    True if entry can be exported to a specific format (can use client.export)
    False if not (must use client.Download)

  """
  if isinstance(entry_or_url, (str, unicode)):
    url = entry_or_url
  else:
    url = entry_or_url.content.src
  can_export = url.find('/Export?') != -1
  return can_export


def safe_move(src, dst):
  """Move file from src to dst.

  If file with same name already exists at dst, rename the new file
  while preserving the extension.

  Returns:
    path to new file.

  """
  new_dir = os.path.abspath(dst)
  ext = googlecl.get_extension_from_path(src)
  if not ext:
    dotted_ext = ''
  else:
    dotted_ext = '.' + ext
  filename = os.path.basename(src).rstrip(dotted_ext)
  rename_num = 1
  new_path = os.path.join(new_dir, filename + dotted_ext)
  while os.path.exists(new_path):
    new_filename = filename + '-' + str(rename_num) + dotted_ext
    new_path = os.path.join(new_dir, new_filename)
  shutil.move(src, new_path)
  return new_path
