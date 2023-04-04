FROM python:3.9-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt

RUN pip3 install -r requirements.txt
CMD python -m spacy download en_core_web_sm
CMD python -m spacy download en_core_web_lg
EXPOSE 7860

COPY . /code

HEALTHCHECK CMD curl --fail http://localhost:7860/_stcore/health

CMD python -m streamlit run presidio_streamlit.py --server.port=7860 --server.address=0.0.0.0