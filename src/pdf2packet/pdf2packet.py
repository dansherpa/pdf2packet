import glob
import sys
import io
import PyPDF4
from pyzxing import BarCodeReader
from PyPDF4 import PdfFileMerger
import os, argparse

from tempfile import TemporaryDirectory
import PIL.Image

parser = argparse.ArgumentParser(
    description='Split PDF files into separate files based on a separator barcode and then combine them into a result packet')
parser.add_argument('filename', metavar='inputfile', type=str,
                    help='Filename or glob to process')
parser.add_argument('--keep-separator', action='store_true',
                    help='Keep separator page in split document')
parser.add_argument('-b', '--brightness', type=int, default=128,
                    help='brightness threshold for barcode preparation (0-255). Default: 128')
parser.add_argument('-v', '--verbose', action='store_true',
                    help='Show verbose processing messages')
parser.add_argument('-d', '--debug', action='store_true',
                    help='Show debug messages')


def merge_pdfs(input_files: list, output_file: str, bookmark: bool = True):
    """
    Merge a list of PDF files and save the combined result into the `output_file`.
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


def make_unique_output_name(output, merge_files, common_docs) -> str:
    for m in merge_files:
        if output in merge_files[m]:
            i = 1
            while True:
                (base, ext) = os.path.splitext(output)
                new_output = "{}.z{:03d}{}".format(base, i, ext)
                if new_output not in merge_files[m]:
                    return new_output
                i += 1
    if output in common_docs:
        i = 1
        while True:
            (base, ext) = os.path.splitext(output)
            new_output = "{}.z{:03d}{}".format(base, i, ext)
            if new_output not in common_docs:
                return new_output
            i += 1
    return output

class PdfQrSplit:
    def __init__(self, filepath: str, verbose: bool, debug: bool, brightness: 128) -> None:
        self.filepath = filepath
        self.verbose = verbose
        self.debug = debug
        self.brightness = brightness
        self.input_pdf = PyPDF4.PdfFileReader(filepath, False)
        self.total_pages = self.input_pdf.getNumPages()
        if verbose:
            print(
                "Processing file {} containing {} pages".format(
                    filepath, self.total_pages
                )
            )

    def write_output(self, last_race, last_label, pdf_writer, common_docs, merge_files, pdfs_count):
        if last_race:
            output = last_label + "-" + last_race + ".pdf"
            output = make_unique_output_name(output, merge_files, common_docs)
            merge_files.setdefault(last_race, []).append(output)
        else:
            output = last_label + ".pdf"
            output = make_unique_output_name(output, merge_files, common_docs)
            if pdf_writer.getNumPages() > 0:
                common_docs.append(output)
        if pdf_writer.getNumPages() > 0:
            if self.verbose:
                print("    End of input - writing {} pages to {}".format(pdf_writer.getNumPages(), output))
            with open(output, 'wb') as output_pdf:
                pdf_writer.write(output_pdf)
            pdfs_count += 1

    def split_qr(self, filepath: str, common_docs, merge_files) -> int:
        """Creates new files based on barcode contents.
        Returns:
            int: Number of generated files.
        """
        pdfs_count = 0
        current_page = 0

        print("Scanning {}".format(filepath), end=" ")
        sys.stdout.flush()
        reader = BarCodeReader()
        pdf_writer = PyPDF4.PdfFileWriter()
        last_label = "999 Unknown"
        last_race = ""

        while current_page != self.total_pages:
            print(current_page + 1, end=" ")
            sys.stdout.flush()
            if self.verbose:
                print("  Analyzing page {}".format((current_page + 1)))

            page = self.input_pdf.getPage(current_page)

            if '/XObject' in page['/Resources']:
                xObject = page['/Resources']['/XObject'].getObject()

                with TemporaryDirectory() as temp_dir:
                    if self.debug:
                        print("    Writing page images to temporary directory {}".format(temp_dir))

                    split = False
                    for obj in xObject:
                        print(".", end=" ")
                        sys.stdout.flush()
                        tgtn = False
                        if xObject[obj]['/Subtype'] == '/Image':
                            data = xObject[obj].getData()

                            if '/FlateDecode' in xObject[obj]['/Filter'] or \
                                    '/DCTDecode' in xObject[obj]['/Filter'] or \
                                    '/JPXDecode' in xObject[obj]['/Filter']:
                                tgtn = temp_dir + "/" + obj[1:] + ".png"
                                img = PIL.Image.open(io.BytesIO(data))
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
                        self.write_output(last_race, last_label, pdf_writer, common_docs, merge_files, pdfs_count)
                        last_label = new_sep
                        last_race = new_race

                        pdf_writer = PyPDF4.PdfFileWriter()
                        # Due to a bug in PyPDF4 PdfFileReader breaks when invoking PdfFileWriter.write - reopen file
                        self.input_pdf = PyPDF4.PdfFileReader(filepath, False)

                        if args.keep_separator:
                            pdf_writer.addPage(page)
                    else:
                        pdf_writer.addPage(page)

            current_page += 1

        self.write_output(last_race, last_label, pdf_writer, common_docs, merge_files, pdfs_count)

        if pdf_writer.getNumPages() > 0:
            for d in common_docs:
                print(".", end=" ")
                sys.stdout.flush()
                for r in merge_files:
                    print(".", end=" ")
                    sys.stdout.flush()
                    merge_files[r].append(d)
            if len(merge_files) == 0:
                print(".")
                print("    No race codes found to create packets for")
                sys.stdout.flush()
            for f in merge_files.keys():
                print(".")
                merge_file = f + ".pdf"
                print("    Merging these files into Result Packet {}:".format(merge_file))
                sys.stdout.flush()
                merge_files[f] = sorted(merge_files[f])
                for r in merge_files[f]:
                    print("        {}".format(r))
                    sys.stdout.flush()
                merge_pdfs(input_files=merge_files[f], output_file=merge_file)

        return pdfs_count


def runit():
    global args
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

    global ofiles, ifiles
    ofiles = 0
    ifiles = 0

    common_docs = []
    merge_files = {}

    for filepath in filepaths:
        splitter = PdfQrSplit(filepath, args.verbose, args.debug, brightness=args.brightness)
        ofiles += splitter.split_qr(filepath, common_docs, merge_files)
        ifiles += 1


if __name__ == '__main__':
    runit()
