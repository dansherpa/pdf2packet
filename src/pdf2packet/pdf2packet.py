import argparse
import glob
import sys
import io
import PyPDF4
from pyzxing import BarCodeReader
from PyPDF4 import PdfFileMerger
import os, argparse

from typing import List
from tempfile import TemporaryDirectory
from PIL import Image

parser = argparse.ArgumentParser(description='Split PDF-file into separate files based on a separator barcode')
parser.add_argument('filename', metavar='inputfile', type=str,
                    help='Filename or glob to process')
parser.add_argument('-p', '--prefix', default="split",
                    help='Prefix for generated PDF files. Default: split')
parser.add_argument('-s', '--separator', default="RPSEQ:",
                    help='Barcode content used to find separator pages. Default: RPSEQ:')
parser.add_argument('-k', '--keep-page', action='store_true',
                    help='Keep separator page in previous document')
parser.add_argument('--keep-page-next', action='store_true',
                    help='Keep separator page in next document')
parser.add_argument('-b', '--brightness', type=int, default=128,
                    help='brightness threshold for barcode preparation (0-255). Default: 128')
parser.add_argument('-v', '--verbose', action='store_true',
                    help='Show verbose processing messages')
parser.add_argument('-d', '--debug', action='store_true',
                    help='Show debug messages')


def merge_pdfs(input_files: list, page_range: tuple, output_file: str, bookmark: bool = True):
    """
    Merge a list of PDF files and save the combined result into the `output_file`.
    `page_range` to select a range of pages (behaving like Python's range() function) from the input files
        e.g (0,2) -> First 2 pages
        e.g (0,6,2) -> pages 1,3,5
    bookmark -> add bookmarks to the output file to navigate directly to the input file section within the output file.
    """
    # strict = False -> To ignore PdfReadError - Illegal Character error
    merger = PdfFileMerger(strict=False)
    for input_file in input_files:
        bookmark_name = os.path.splitext(os.path.basename(input_file))[0] if bookmark else None
        # pages To control which pages are appended from a particular file.
        merger.append(fileobj=open(input_file, 'rb'), import_bookmarks=False, bookmark=bookmark_name)
    # Insert the pdf at specific page
    merger.write(fileobj=open(output_file, 'wb'))
    merger.close()


def extract_barcodes(results) -> (str, str):
    sep = ""
    race = ""
    for r in results:
        if 'parsed' in r:
            barcode = r['parsed'].decode('ascii')
            if "RPSEQ:" in barcode:
                sep = barcode.partition(":")[2]
            if "007" in barcode:
                barcode = "RC: N0276"
            if "RC:" in barcode:
                race = barcode.partition(": ")[2]
    return sep, race


class PdfQrSplit:
    def __init__(self, filepath: str, verbose: bool, debug: bool, brightness: 128) -> None:
        self.filepath = filepath
        self.verbose = verbose
        self.debug = debug
        self.brightness = brightness
        self.input_pdf = PyPDF4.PdfFileReader(filepath, "rb")
        self.total_pages = self.input_pdf.getNumPages()
        if verbose:
            print(
                "Processing file {} containing {} pages".format(
                    filepath, self.total_pages
                )
            )

    def split_qr(self, split_text: str, ifiles: int) -> int:
        """Creates new files based on barcode contents.
        Args:
            split_text: Barcode content to recognize a separator page
        Returns:
            int: Number of generated files.
        """
        pdfs_count = 0
        current_page = 0
        common_docs = []
        merge_files = {}

        reader = BarCodeReader()
        pdf_writer = PyPDF4.PdfFileWriter()
        last_label = "999 Unknown"
        last_race = ""

        while current_page != self.total_pages:

            if self.verbose:
                print("  Analyzing page {}".format((current_page + 1)))

            page = self.input_pdf.getPage(current_page)

            xObject = page['/Resources']['/XObject'].getObject()

            with TemporaryDirectory() as temp_dir:
                if self.debug:
                    print("    Writing page images to temporary directory {}".format(temp_dir))

                split = False
                for obj in xObject:
                    tgtn = False
                    if xObject[obj]['/Subtype'] == '/Image':
                        data = xObject[obj].getData()

                        if '/FlateDecode' in xObject[obj]['/Filter'] or \
                                '/DCTDecode' in xObject[obj]['/Filter'] or \
                                '/JPXDecode' in xObject[obj]['/Filter']:
                            tgtn = temp_dir + "/" + obj[1:] + ".png"
                            img = Image.open(io.BytesIO(data))
                            fn = lambda x: 255 if x > self.brightness else 0
                            img = img.convert('L').point(fn, mode='1')
                            img.save(tgtn)
                        elif self.debug:
                            print(f"      Unknown filter type {xObject[obj]['/Filter']}")

                        if tgtn:
                            if self.debug:
                                print("      Wrote image {}; Checking for separator barcode".format(tgtn))
                            sep, race = extract_barcodes(reader.decode(tgtn))
                            if sep:
                                new_sep = sep
                                new_race = race
                                if self.debug:
                                    print("        Found separator barcode")
                                    print("        Label:", new_sep)
                                    print("        Race:", new_race)
                                split = True
                if split:
                    if args.keep_page:
                        pdf_writer.addPage(page)

                    if last_race:
                        output = last_label + "-" + last_race + ".pdf"
                        merge_files.setdefault(last_race, []).append(output)
                    else:
                        output = last_label + ".pdf"
                        if pdf_writer.getNumPages() > 0:
                            common_docs.append(output)
                    last_label = new_sep
                    last_race = new_race
                    if pdf_writer.getNumPages() > 0:
                        if self.verbose:
                            print(
                                "    Found separator - writing {} pages to {}".format(pdf_writer.getNumPages(), output))
                        with open(output, 'wb') as output_pdf:
                            pdf_writer.write(output_pdf)
                        pdfs_count += 1

                    pdf_writer = PyPDF4.PdfFileWriter()
                    # Due to a bug in PyPDF4 PdfFileReader breaks when invoking PdfFileWriter.write - reopen file
                    self.input_pdf = PyPDF4.PdfFileReader(filepath, "rb")

                    if args.keep_page_next:
                        pdf_writer.addPage(page)
                else:
                    pdf_writer.addPage(page)

            current_page += 1

        if last_race:
            output = last_label + "-" + last_race + ".pdf"
            merge_files.setdefault(last_race, []).append(output)
        else:
            output = last_label + ".pdf"
            if pdf_writer.getNumPages() > 0:
                common_docs.append(output)
        if pdf_writer.getNumPages() > 0:
            if self.verbose:
                print("    End of input - writing {} pages to {}".format(pdf_writer.getNumPages(), output))
                for d in common_docs:
                    for r in merge_files:
                        merge_files[r].append(d)
                for f in merge_files.keys():
                    merge_file = f + ".pdf"
                    print("    Merging these files into {}:".format(merge_file))
                    merge_files[f] = sorted(merge_files[f])
                    for r in merge_files[f]:
                        print("        {}".format(r))
                    merge_pdfs(input_files=merge_files[f], page_range=(1,999), output_file=merge_file)
            with open(output, 'wb') as output_pdf:
                pdf_writer.write(output_pdf)
            pdfs_count += 1

        return pdfs_count


args = parser.parse_args()

if args.debug:
    args.verbose = True

if args.brightness < 0:
    args.brightness = 0
if args.brightness > 255:
    args.brightness = 255

filepaths = glob.glob(args.filename)
if not filepaths:
    sys.exit("Error: no file found, check the documentation for more info.")

ofiles = 0
ifiles = 0

for filepath in filepaths:
    splitter = PdfQrSplit(filepath, args.verbose, args.debug, brightness=args.brightness)
    ofiles += splitter.split_qr(args.separator, ifiles)
    ifiles += 1

print(
    "Split {} given files into {} files".format(
        ifiles, ofiles
    )
)
