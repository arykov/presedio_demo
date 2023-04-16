"""Streamlit app for Presidio."""
import os
from json import JSONEncoder
from typing import List

import pandas as pd
import spacy
import streamlit as st
from annotated_text import annotated_text
from presidio_analyzer import AnalyzerEngine, RecognizerResult, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from flair_recognizer import FlairRecognizer
from transformers_rec import (
    STANFORD_COFIGURATION,
    TransformersRecognizer,
    BERT_DEID_CONFIGURATION,
)

from openai_fake_data_generator import (
    set_openai_key,
    call_completion_model,
    create_prompt,
)


# Helper methods
@st.cache_resource
def analyzer_engine(model_path: str):
    """Return AnalyzerEngine.

    :param model_path: Which model to use for NER:
        "StanfordAIMI/stanford-deidentifier-base",
        "obi/deid_roberta_i2b2",
        "en_core_web_lg"
    """

    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()

    # Set up NLP Engine according to the model of choice
    if model_path == "en_core_web_lg":
        if not spacy.util.is_package("en_core_web_lg"):
            spacy.cli.download("en_core_web_lg")
        nlp_configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
        }
    elif model_path == "flair/ner-english-large":
        flair_recognizer = FlairRecognizer()
        nlp_configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
        registry.add_recognizer(flair_recognizer)
        registry.remove_recognizer("SpacyRecognizer")
    else:
        if not spacy.util.is_package("en_core_web_sm"):
            spacy.cli.download("en_core_web_sm")
        # Using a small spaCy model + a HF NER model
        transformers_recognizer = TransformersRecognizer(model_path=model_path)
        registry.remove_recognizer("SpacyRecognizer")
        if model_path == "StanfordAIMI/stanford-deidentifier-base":
            transformers_recognizer.load_transformer(**STANFORD_COFIGURATION)
        elif model_path == "obi/deid_roberta_i2b2":
            transformers_recognizer.load_transformer(**BERT_DEID_CONFIGURATION)

        # Use small spaCy model, no need for both spacy and HF models
        # The transformers model is used here as a recognizer, not as an NlpEngine
        nlp_configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }

        registry.add_recognizer(transformers_recognizer)

    nlp_engine = NlpEngineProvider(nlp_configuration=nlp_configuration).create_engine()

    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, registry=registry)
    return analyzer


@st.cache_resource
def anonymizer_engine():
    """Return AnonymizerEngine."""
    return AnonymizerEngine()


@st.cache_data
def get_supported_entities():
    """Return supported entities from the Analyzer Engine."""
    return analyzer_engine(st_model).get_supported_entities()


@st.cache_data
def analyze(**kwargs):
    """Analyze input using Analyzer engine and input arguments (kwargs)."""
    if "entities" not in kwargs or "All" in kwargs["entities"]:
        kwargs["entities"] = None
    return analyzer_engine(st_model).analyze(**kwargs)


def anonymize(text: str, analyze_results: List[RecognizerResult]):
    """Anonymize identified input using Presidio Anonymizer.

    :param text: Full text
    :param analyze_results: list of results from presidio analyzer engine
    """

    if st_operator == "mask":
        operator_config = {
            "type": "mask",
            "masking_char": st_mask_char,
            "chars_to_mask": st_number_of_chars,
            "from_end": False,
        }

    # Define operator config
    elif st_operator == "encrypt":
        operator_config = {"key": st_encrypt_key}
    elif st_operator == "highlight":
        operator_config = {"lambda": lambda x: x}
    else:
        operator_config = None

    # Change operator if needed as intermediate step
    if st_operator == "highlight":
        operator = "custom"
    elif st_operator == "synthesize":
        operator = "replace"
    else:
        operator = st_operator

    res = anonymizer_engine().anonymize(
        text,
        analyze_results,
        operators={"DEFAULT": OperatorConfig(operator, operator_config)},
    )
    return res


def annotate(text: str, analyze_results: List[RecognizerResult]):
    """
    Highlights every identified entity on top of the text.
    :param text: full text
    :param analyze_results: list of analyzer results.
    """
    tokens = []

    # Use the anonymizer to resolve overlaps
    results = anonymize(text, analyze_results)

    # sort by start index
    results = sorted(results.items, key=lambda x: x.start)
    for i, res in enumerate(results):
        if i == 0:
            tokens.append(text[: res.start])

        # append entity text and entity type
        tokens.append((text[res.start : res.end], res.entity_type))

        # if another entity coming i.e. we're not at the last results element, add text up to next entity
        if i != len(results) - 1:
            tokens.append(text[res.end : results[i + 1].start])
        # if no more entities coming, add all remaining text
        else:
            tokens.append(text[res.end :])
    return tokens


def create_fake_data(
    text: str,
    analyze_results: List[RecognizerResult],
    openai_key: str,
    openai_model_name: str,
):
    """Creates a synthetic version of the text using OpenAI APIs"""
    if not openai_key:
        return "Please provide your OpenAI key"
    results = anonymize(text, analyze_results)
    set_openai_key(openai_key)
    prompt = create_prompt(results.text)
    fake = call_openai_api(prompt, openai_model_name)
    return fake


@st.cache_data
def call_openai_api(prompt: str, openai_model_name: str) -> str:
    fake_data = call_completion_model(prompt, model=openai_model_name)
    return fake_data


st.set_page_config(page_title="Presidio demo", layout="wide")

# Sidebar
st.sidebar.header(
    """
PII De-Identification with Microsoft Presidio
"""
)

st.sidebar.info(
    "Presidio is an open source customizable framework for PII detection and de-identification\n"
    "[Code](https://aka.ms/presidio) | "
    "[Tutorial](https://microsoft.github.io/presidio/tutorial/) | "
    "[Installation](https://microsoft.github.io/presidio/installation/) | "
    "[FAQ](https://microsoft.github.io/presidio/faq/)",
    icon="ℹ️",
)

st.sidebar.markdown(
    "[![Pypi Downloads](https://img.shields.io/pypi/dm/presidio-analyzer.svg)](https://img.shields.io/pypi/dm/presidio-analyzer.svg)"
    "[![MIT license](https://img.shields.io/badge/license-MIT-brightgreen.svg)](http://opensource.org/licenses/MIT)"
    "![GitHub Repo stars](https://img.shields.io/github/stars/microsoft/presidio?style=social)"
)

st_model = st.sidebar.selectbox(
    "NER model for PII detection",
    [
        "StanfordAIMI/stanford-deidentifier-base",
        "obi/deid_roberta_i2b2",
        "flair/ner-english-large",
        "en_core_web_lg",
    ],
    index=1,
    help="""
    Select which Named Entity Recognition (NER) model to use for PII detection, in parallel to rule-based recognizers.
    Presidio supports multiple NER packages off-the-shelf, such as spaCy, Huggingface, Stanza and Flair.
    """,
)
st.sidebar.markdown("> Note: Models might take some time to download. ")

st_operator = st.sidebar.selectbox(
    "De-identification approach",
    ["redact", "replace", "synthesize", "highlight", "mask", "hash", "encrypt"],
    index=1,
    help="""
    Select which manipulation to the text is requested after PII has been identified.\n
    - Redact: Completely remove the PII text\n
    - Replace: Replace the PII text with a constant, e.g. <PERSON>\n
    - Synthesize: Replace with fake values (requires an OpenAI key)\n
    - Highlight: Shows the original text with PII highlighted in colors\n
    - Mask: Replaces a requested number of characters with an asterisk (or other mask character)\n
    - Hash: Replaces with the hash of the PII string\n
    - Encrypt: Replaces with an AES encryption of the PII string, allowing the process to be reversed
         """,
)

if st_operator == "mask":
    st_number_of_chars = st.sidebar.number_input(
        "number of chars", value=15, min_value=0, max_value=100
    )
    st_mask_char = st.sidebar.text_input("Mask character", value="*", max_chars=1)
elif st_operator == "encrypt":
    st_encrypt_key = st.sidebar.text_input("AES key", value="WmZq4t7w!z%C&F)J")
elif st_operator == "synthesize":
    st_openai_key = st.sidebar.text_input(
        "OPENAI_KEY",
        value=os.getenv("OPENAI_KEY", default=""),
        help="See https://help.openai.com/en/articles/4936850-where-do-i-find-my-secret-api-key for more info.",
        type="password",
    )
    st_openai_model = st.sidebar.text_input(
        "OpenAI model for text synthesis",
        value="text-davinci-003",
        help="See more here: https://platform.openai.com/docs/models/",
    )
st_threshold = st.sidebar.slider(
    label="Acceptance threshold",
    min_value=0.0,
    max_value=1.0,
    value=0.35,
    help="Define the threshold for accepting a detection as PII. See more here: ",
)

st_return_decision_process = st.sidebar.checkbox(
    "Add analysis explanations to findings", value=False,
    help="Add the decision process to the output table. More information can be found here: https://microsoft.github.io/presidio/analyzer/decision_process/"
)

st_entities = st.sidebar.multiselect(
    label="Which entities to look for?",
    options=get_supported_entities(),
    default=list(get_supported_entities()),
    help="Limit the list of PII entities detected. This list is dynamic and based on the NER model and registered recognizers. More information can be found here: https://microsoft.github.io/presidio/analyzer/adding_recognizers/"
)

# Main panel
analyzer_load_state = st.info("Starting Presidio analyzer...")
engine = analyzer_engine(model_path=st_model)
analyzer_load_state.empty()

# Read default text
with open("demo_text.txt") as f:
    demo_text = f.readlines()

# Create two columns for before and after
col1, col2 = st.columns(2)

# Before:
col1.subheader("Input string:")
st_text = col1.text_area(
    label="Enter text",
    value="".join(demo_text),
    height=400,
)

st_analyze_results = analyze(
    text=st_text,
    entities=st_entities,
    language="en",
    score_threshold=st_threshold,
    return_decision_process=st_return_decision_process,
)

# After
if st_operator not in ("highlight", "synthesize"):
    with col2:
        st.subheader(f"Output")
        st_anonymize_results = anonymize(st_text, st_analyze_results)
        st.text_area(label="De-identified", value=st_anonymize_results.text, height=400)
elif st_operator == "synthesize":
    with col2:
        st.subheader(f"OpenAI Generated output")
        fake_data = create_fake_data(
            st_text,
            st_analyze_results,
            openai_key=st_openai_key,
            openai_model_name=st_openai_model,
        )
        st.text_area(label="Synthetic data", value=fake_data, height=400)
else:
    st.subheader("Highlighted")
    annotated_tokens = annotate(st_text, st_analyze_results)
    # annotated_tokens
    annotated_text(*annotated_tokens)


# json result
class ToDictEncoder(JSONEncoder):
    """Encode dict to json."""

    def default(self, o):
        """Encode to JSON using to_dict."""
        return o.to_dict()


# table result
st.subheader(
    "Findings" if not st_return_decision_process else "Findings with decision factors"
)
if st_analyze_results:
    df = pd.DataFrame.from_records([r.to_dict() for r in st_analyze_results])
    df["text"] = [st_text[res.start : res.end] for res in st_analyze_results]

    df_subset = df[["entity_type", "text", "start", "end", "score"]].rename(
        {
            "entity_type": "Entity type",
            "text": "Text",
            "start": "Start",
            "end": "End",
            "score": "Confidence",
        },
        axis=1,
    )
    df_subset["Text"] = [st_text[res.start : res.end] for res in st_analyze_results]
    if st_return_decision_process:
        analysis_explanation_df = pd.DataFrame.from_records(
            [r.analysis_explanation.to_dict() for r in st_analyze_results]
        )
        df_subset = pd.concat([df_subset, analysis_explanation_df], axis=1)
    st.dataframe(df_subset.reset_index(drop=True), use_container_width=True)
else:
    st.text("No findings")
