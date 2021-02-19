"""
Parla Clarin generation
"""
import pandas as pd
import progressbar, copy
from lxml import etree
from riksdagen_corpus.utils import infer_metadata
from riksdagen_corpus.download import get_blocks, fetch_files
from riksdagen_corpus.curation import apply_curations
from riksdagen_corpus.segmentation import apply_instances
from riksdagen_corpus.db import filter_db, year_iterator

# Generate parla clarin header
def _pc_header(metadata):
    teiHeader = etree.Element("teiHeader")
    
    # fileDesc
    fileDesc = etree.SubElement(teiHeader, "fileDesc")
    
    titleStmt = etree.SubElement(fileDesc, "titleStmt")
    title = etree.SubElement(titleStmt, "title")
    title.text = metadata.get("document_title", "N/A")
    
    if "edition" in metadata:
        editionStmt = etree.SubElement(fileDesc, "editionStmt")
        edition = etree.SubElement(editionStmt, "edition")
        edition.text = metadata.get("edition", "N/A")

    extent = etree.SubElement(fileDesc, "extent")
    publicationStmt = etree.SubElement(fileDesc, "publicationStmt")
    authority = etree.SubElement(publicationStmt, "authority")
    authority.text = metadata.get("authority", "N/A")
    
    sourceDesc = etree.SubElement(fileDesc, "sourceDesc")
    sourceBibl = etree.SubElement(sourceDesc, "bibl")
    sourceTitle = etree.SubElement(sourceBibl, "title")
    sourceTitle.text = metadata.get("document_title", "N/A")
    
    # encodingDesc
    encodingDesc = etree.SubElement(teiHeader, "encodingDesc")
    editorialDecl = etree.SubElement(encodingDesc, "editorialDecl")
    correction = etree.SubElement(editorialDecl, "correction")
    correction_p = etree.SubElement(correction, "p")
    correction_p.text = metadata.get("correction", "No correction of source texts was performed.")
    
    return teiHeader
    
def create_parlaclarin(teis, metadata):
    if type(teis) != list:
        tei = teis
        return create_parlaclarin([tei], metadata)
    
    teiCorpus = etree.Element("teiCorpus", xmlns="http://www.tei-c.org/ns/1.0")
    teiHeader = _pc_header(metadata)
    teiCorpus.append(teiHeader)
    
    for tei in teis:
        teiCorpus.append(tei)
    
    teiCorpusTree = etree.ElementTree(teiCorpus)
    
    for xml_element in teiCorpusTree.iter():
        content = xml_element.xpath('normalize-space()')
        if not content:
            xml_element.getparent().remove(xml_element)
            
    s = etree.tostring(teiCorpusTree, pretty_print=True, encoding="utf-8", xml_declaration=True).decode("utf-8")
    return s
    
def create_tei(root, metadata):
    """
    Create a Parla-Clarin TEI element from a list of segments.

    Args:
        txts: a list of lists of strings, corresponds to content blocks and paragraphs, respectively.
        metadata: Metadata of the parliamentary session
    """
    metadata = copy.deepcopy(metadata)
    
    tei = etree.Element("TEI")
    protocol_id = root.attrib["id"]
    metadata["document_title"] = protocol_id.replace("_", " ").split("-")[0].replace("prot", "Protokoll")
    documentHeader = _pc_header(metadata)
    tei.append(documentHeader)
    
    text = etree.SubElement(tei, "text")
    front = etree.SubElement(text, "front")
    preface = etree.SubElement(front, "div", type="preface")
    etree.SubElement(preface, "head").text = protocol_id.split(".")[0]
    if "date" not in metadata:
        year = metadata.get("year", 2020)
        metadata["date"] = str(year) + "-01-01"
        
    etree.SubElement(preface, "docDate", when=metadata["date"]).text = metadata.get("date", "2020-01-01")

    body = etree.SubElement(text, "body")
    body_div = etree.SubElement(body, "div")
    
    current_speaker = None
    u = None
    prev_u = None

    for content_block in root:
        content_txt = '\n'.join(content_block.itertext())
        is_empty = content_txt == ""
        cb_ix = content_block.attrib["id"]
        segmentation = content_block.attrib.get("segmentation", None)
        if segmentation == "metadata":
            if prev_u is None:
                prev_u = u
                u = None
            for textblock in content_block:
                note = etree.SubElement(body_div, "note")
                note.text = textblock.text
                note.attrib["{http://www.w3.org/XML/1998/namespace}id"] = textblock.attrib.get("id", None)
        elif segmentation == "note":
            for textblock in content_block:
                note = etree.SubElement(body_div, "note")
                note.text = textblock.text
                note.attrib["{http://www.w3.org/XML/1998/namespace}id"] = textblock.attrib.get("id", None)
        else:
            for textblock in content_block:
                tb_segmentation = textblock.attrib.get("segmentation", None)
                if tb_segmentation == "speech_start":
                    prev_u = None
                    current_speaker = textblock.attrib.get("who", None)
                    note = etree.SubElement(body_div, "note", type="speaker")                    
                    u = etree.SubElement(body_div, "u")
                    if current_speaker is not None:
                        u.attrib["who"] = current_speaker
                    else:
                        u.attrib["who"] = "unknown"
                    
                    # Introduction under <note> tag
                    # Actual speech under <u> tag
                    paragraph = textblock.text.split(":")
                    introduction = paragraph[0] + ":"
                    note.text = introduction
                    note.attrib["{http://www.w3.org/XML/1998/namespace}id"] = textblock.attrib.get("id", None)
                    if len(paragraph) > 1:
                        rest_of_paragraph = ":".join(paragraph[1:]).strip()
                        if len(rest_of_paragraph) > 0:
                            seg = etree.SubElement(u, "seg")
                            seg.text = rest_of_paragraph
                elif tb_segmentation == "note":
                    if prev_u is None:
                        prev_u = u
                        u = None
                    note = etree.SubElement(body_div, "note")
                    note.text = textblock.text
                    note.attrib["{http://www.w3.org/XML/1998/namespace}id"] = textblock.attrib.get("id", None)
                elif tb_segmentation == "metadata":
                    if prev_u is None:
                        prev_u = u
                        u = None
                    note = etree.SubElement(body_div, "note")
                    note.text = textblock.text
                else:
                    paragraph = textblock.text
                    if paragraph != "":
                        if u is not None:
                            seg = etree.SubElement(u, "seg")
                            seg.text = paragraph
                            seg.attrib["{http://www.w3.org/XML/1998/namespace}id"] = textblock.attrib.get("id", None)
                        elif prev_u is not None:
                            prev_u.attrib["next"] = "cont"
                            u = etree.SubElement(body_div, "u")
                            if current_speaker is not None:
                                u.attrib["who"] = current_speaker
                            else:
                                u.attrib["who"] = "unknown"
                            u.attrib["prev"] = "cont"
                            seg = etree.SubElement(u, "seg")
                            seg.text = paragraph
                            note.attrib["{http://www.w3.org/XML/1998/namespace}id"] = textblock.attrib.get("id", None)
                        else:
                            note = etree.SubElement(body_div, "note")
                            note.text = paragraph
                            note.attrib["{http://www.w3.org/XML/1998/namespace}id"] = textblock.attrib.get("id", None)
    return tei

def gen_parlaclarin_corpus(protocol_db, archive, instance_db, curation_db=None, corpus_metadata=dict(), str_output=True):
    teis = []
    #print("Pages in total", protocol_db["pages"].sum())
    
    for ix, package in list(protocol_db.iterrows()):
        protocol_id = package["protocol_id"]
        pages = package["pages"]
        metadata = infer_metadata(protocol_id)
        protocol = get_blocks(protocol_id, archive)
        protocol = apply_curations(protocol, curation_db)
        protocol = apply_instances(protocol, instance_db)
        tei = create_tei(protocol, metadata)
        teis.append(tei)
    
    corpus_metadata["edition"] = "0.1.0"
    corpus = create_parlaclarin(teis, corpus_metadata)
    return corpus

def parlaclarin_workflow(file_db, archive, curations=None, segmentations=None):
    for corpus_year, package_ids, year_db in year_iterator(file_db):
        print("Generate corpus for year", corpus_year)
        current_instances = pd.merge(segmentations, year_db, on=['protocol_id'])
        current_curations = pd.merge(curations, year_db, on=['protocol_id'])

        corpus_metadata = dict(
            document_title="Riksdagens protocols " + str(corpus_year),
            authority="National Library of Sweden and the WESTAC project",
            correction="Some data curation was done. It is documented in db/curation/instances"
        )
        parla_clarin_str = gen_parlaclarin_corpus(year_db, archive, current_instances, corpus_metadata=corpus_metadata, curation_db=current_curations)
        
        parlaclarin_path = "data/parla-clarin/" + "corpus" + str(corpus_year) + ".xml"
        f = open(parlaclarin_path, "w")
        f.write(parla_clarin_str)
        f.close()

def parlaclarin_workflow_individual(file_db, archive, curations=None, segmentations=None):
    for corpus_year, package_ids, year_db in year_iterator(file_db):
        print("Generate corpus for year", corpus_year)
        current_instances = pd.merge(segmentations, year_db, on=['protocol_id'])
        current_curations = pd.merge(curations, year_db, on=['protocol_id'])

        corpus_metadata = dict(
            document_title="Riksdagens protocols " + str(corpus_year),
            authority="National Library of Sweden and the WESTAC project",
            correction="Some data curation was done. It is documented in db/curation/instances"
        )

        year_db = file_db[file_db["year"] ==corpus_year]
        for ix, row in progressbar.progressbar(list(year_db.iterrows())):
            df = pd.DataFrame([row], columns = year_db.columns)
            protocol_id = row["protocol_id"]
            parla_clarin_str = gen_parlaclarin_corpus(df, archive, current_instances, corpus_metadata=corpus_metadata, curation_db=current_curations)
            
            parlaclarin_path = "data/new-parlaclarin/" + protocol_id+ ".xml"
            f = open(parlaclarin_path, "w")
            f.write(parla_clarin_str)
            f.close()

