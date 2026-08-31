from transient_pipeline.tables import parse_votable_tabledata


def test_votable_tabledata_parser():
    text = '''<?xml version="1.0"?><VOTABLE xmlns="http://www.ivoa.net/xml/VOTable/v1.3"><RESOURCE><TABLE>
    <FIELD name="source_id" datatype="long"/><FIELD name="ra_icrs" datatype="double"/><FIELD name="dec_icrs" datatype="double"/>
    <DATA><TABLEDATA><TR><TD>123</TD><TD>1.5</TD><TD>-2.5</TD></TR></TABLEDATA></DATA></TABLE></RESOURCE></VOTABLE>'''
    assert parse_votable_tabledata(text) == [{"source_id":"123","ra_icrs":"1.5","dec_icrs":"-2.5"}]
