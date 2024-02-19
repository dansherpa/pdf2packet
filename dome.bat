py -m build
py -m twine upload --repository pypi dist/pdf2packet-0.0.1-*
py -m twine upload --repository pypi dist/pdf2packet-0.0.1.*

REM python -m venv c:\dpk.test
REM do this
REM c:\dpk.test\Scripts\activate
REM python c:\dpk.test\Lib\site-packages\pdf2packet\pdf2packet.py
REM pip install pdf2packet
REM REM pip install pdf2packet --upgrade
REM deactivate
