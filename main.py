import os
import time
import requests
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics import TextAnalyticsClient
from azure.cognitiveservices.speech import SpeechConfig, SpeechRecognizer, AudioConfig, ResultReason, AutoDetectSourceLanguageConfig, ServicePropertyChannel
from tqdm import tqdm
from docx import Document
import PyPDF2
import pypandoc
from pydub import AudioSegment

def split_text(text, max_length):
    """Divide el texto en partes más pequeñas de longitud máxima `max_length`."""
    return [text[i:i + max_length] for i in range(0, len(text), max_length)]

def read_txt(file_path):
    """Lee el contenido de un archivo .txt."""
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def read_docx(file_path):
    """Lee el contenido de un archivo .docx."""
    doc = Document(file_path)
    return '\n'.join([para.text for para in doc.paragraphs])

def read_pdf(file_path):
    """Lee el contenido de un archivo .pdf."""
    with open(file_path, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        text = ''
        for page in reader.pages:
            text += page.extract_text()
        return text

def read_doc(file_path):
    """Convierte y lee el contenido de un archivo .doc."""
    output = pypandoc.convert_file(file_path, 'docx')
    return read_docx(output)

def read_file(file_path):
    """Determina el tipo de archivo y lee su contenido."""
    _, file_extension = os.path.splitext(file_path)
    if file_extension == '.txt':
        return read_txt(file_path)
    elif file_extension == '.docx':
        return read_docx(file_path)
    elif file_extension == '.pdf':
        return read_pdf(file_path)
    elif file_extension == '.doc':
        return read_doc(file_path)
    else:
        raise ValueError(f"Formato de archivo no soportado: {file_extension}")

def convert_audio_to_wav(input_path, output_path):
    """Convierte un archivo de audio a formato WAV."""
    audio = AudioSegment.from_file(input_path)
    audio.export(output_path, format='wav')

def transcribe_audio(file_path, output_path):
    """Transcribe un archivo de audio y guarda el resultado en un archivo .txt."""
    load_dotenv()
    speech_key = os.getenv('AZURE_SPEECH_KEY')
    service_region = os.getenv('AZURE_SERVICE_REGION')
    model_id = "e418c4a9-9937-4db7-b2c9-8afbff72d950"  # ID del modelo Whisper Large V2

    # Convertir el archivo de audio a formato WAV
    wav_path = os.path.splitext(file_path)[0] + '.wav'
    convert_audio_to_wav(file_path, wav_path)

    # Configurar el cliente de transcripción
    speech_config = SpeechConfig(subscription=speech_key, region=service_region)
    speech_config.set_service_property(name="modelId", value=model_id, channel=ServicePropertyChannel.UriQueryParameter)
    auto_detect_source_language_config = AutoDetectSourceLanguageConfig(
        languages=["en-US", "es-ES"]
    )

    audio_config = AudioConfig(filename=wav_path)
    recognizer = SpeechRecognizer(speech_config=speech_config, audio_config=audio_config, auto_detect_source_language_config=auto_detect_source_language_config)

    all_results = []
    done = False

    def handle_final_result(evt):
        nonlocal done
        if evt.result.reason == ResultReason.RecognizedSpeech:
            all_results.append(evt.result.text)
        elif evt.result.reason == ResultReason.NoMatch:
            print("No se reconoció ninguna palabra.")
        elif evt.result.reason == ResultReason.Canceled:
            cancellation_details = evt.result.cancellation_details
            if cancellation_details.reason == ResultReason.EndOfStream:
                print("Transcripción completada.")
            else:
                print(f"Transcripción cancelada: {cancellation_details.reason}")
                if cancellation_details.reason == ResultReason.Error:
                    print(f"Error: {cancellation_details.error_details}")
            done = True

    def stop_recognition(evt):
        nonlocal done
        done = True

    recognizer.recognized.connect(handle_final_result)
    recognizer.canceled.connect(handle_final_result)
    recognizer.session_stopped.connect(stop_recognition)

    recognizer.start_continuous_recognition()

    # Mostrar barra de progreso durante la transcripción
    start_time = time.time()
    with tqdm(desc="Transcribiendo audio...") as pbar:
        while not done:
            elapsed_time = time.time() - start_time
            pbar.set_postfix(elapsed=f"{elapsed_time:.2f}s")
            time.sleep(1)
            pbar.update(1)

    recognizer.stop_continuous_recognition_async().get()

    with open(output_path, 'w', encoding='utf-8') as file:
        file.write(' '.join(all_results))

def procesar_opciones_usuario(file_path, ai_client):
    """Procesa las opciones del usuario para el archivo de texto generado."""
    print("Seleccione los resultados que desea visualizar (separados por comas):")
    print("1. Palabras clave del documento")
    print("2. Entidades")
    print("3. Enlaces")
    print("4. Resumen abstractivo")
    user_choices = input("Ingrese los números de las opciones seleccionadas: ").split(',')

    text = read_file(file_path)
    text_parts = split_text(text, 5120)

    combined_text = ""
    all_phrases = set()
    all_entities = set()
    all_linked_entities = set()
    sentiments = []

    with tqdm(total=len(text_parts), desc="procesando solicitud...") as pbar:
        for part in text_parts:
            detected_language = ai_client.detect_language(documents=[part])[0]
            language = detected_language.primary_language.iso6391_name

            sentiment_analysis = ai_client.analyze_sentiment(documents=[part])[0]
            sentiments.append(sentiment_analysis.sentiment)

            if '1' in user_choices:
                phrases = ai_client.extract_key_phrases(documents=[part])[0].key_phrases
                all_phrases.update(phrases)

            if '2' in user_choices:
                entities = ai_client.recognize_entities(documents=[part])[0].entities
                all_entities.update((entity.text, entity.category) for entity in entities)

            if '3' in user_choices:
                linked_entities = ai_client.recognize_linked_entities(documents=[part])[0].entities
                all_linked_entities.update((linked_entity.name, linked_entity.url) for linked_entity in linked_entities)

            combined_text += part + " "
            pbar.update(1)
            time.sleep(0.1)

    summary = ""
    if '4' in user_choices:
        poller = ai_client.begin_abstract_summary(
            documents=[combined_text],
            language=language,
            display_name="Resumen abstractivo",
            sentence_count=20
        )
        abstract_summary_results = poller.result()
        for result in abstract_summary_results:
            if result.kind == "AbstractiveSummarization":
                paragraphs = []
                current_paragraph = []
                for summary in result.summaries:
                    current_paragraph.append(summary.text)
                    if len(current_paragraph) >= 3:
                        paragraphs.append(" ".join(current_paragraph))
                        current_paragraph = []
                if current_paragraph:
                    paragraphs.append(" ".join(current_paragraph))
                summary = "\n\n".join(paragraphs)
            elif result.is_error:
                print("...Is an error with code '{}' and message '{}'".format(
                    result.error.code, result.error.message
                ))

    print("\n-------------\nResultados para el documento: " + os.path.basename(file_path))
    print("\nIdioma detectado: {}".format(detected_language.primary_language.name))
    print("\nSentimiento: {}".format(max(set(sentiments), key=sentiments.count)))
    if '1' in user_choices and all_phrases:
        print("\nPalabras clave del documento:")
        for phrase in all_phrases:
            print('\t{}'.format(phrase))
    if '2' in user_choices and all_entities:
        print("\nEntidades:")
        for entity, category in all_entities:
            print('\t{} ({})'.format(entity, category))
    if '3' in user_choices and all_linked_entities:
        print("\nEnlaces:")
        for name, url in all_linked_entities:
            print('\t{} ({})'.format(name, url))
    if '4' in user_choices:
        print("\nResumen abstractivo:")
        print(f"{summary}\n")

def main():
    try:
        load_dotenv()
        ai_endpoint = os.getenv('AI_SERVICE_ENDPOINT')
        ai_key = os.getenv('AI_SERVICE_KEY')

        if not ai_endpoint or not ai_key:
            raise ValueError("Las variables de entorno AI_SERVICE_ENDPOINT y AI_SERVICE_KEY deben estar configuradas.")

        credential = AzureKeyCredential(ai_key)
        ai_client = TextAnalyticsClient(endpoint=ai_endpoint, credential=credential)

        print("Seleccione la fuente de entrada:")
        print("1. Archivo de texto (txt, doc, pdf)")
        print("2. Archivo de audio (mp3, wav, m4a)")
        source_choice = input("Ingrese el número de la opción seleccionada: ")

        if source_choice == '1':
            reviews_folder = 'reviews'
            for file_name in os.listdir(reviews_folder):
                if file_name == '.DS_Store':
                    continue

                file_path = os.path.join(reviews_folder, file_name)
                try:
                    print('\n-------------\n' + file_name)
                    procesar_opciones_usuario(file_path, ai_client)
                except (UnicodeDecodeError, ValueError) as e:
                    print(f"Error al leer el archivo {file_name}: {e}")

        elif source_choice == '2':
            audio_folder = 'audio'
            for file_name in os.listdir(audio_folder):
                if file_name == '.DS_Store':
                    continue

                file_path = os.path.join(audio_folder, file_name)
                output_path = os.path.join('reviews', os.path.splitext(file_name)[0] + '.txt')
                try:
                    print('\nTranscribiendo archivo de audio: ' + file_name)
                    transcribe_audio(file_path, output_path)
                    print('Transcripción completada y guardada en: ' + output_path)
                    procesar_opciones_usuario(output_path, ai_client)
                except Exception as e:
                    print(f"Error al transcribir el archivo {file_name}: {e}")

    except Exception as ex:
        print(ex)

if __name__ == "__main__":
    main()