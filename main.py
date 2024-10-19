import os
import time
import requests
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics import TextAnalyticsClient
from azure.cognitiveservices.speech import (
    SpeechConfig, SpeechRecognizer, AudioConfig, ResultReason,
    AutoDetectSourceLanguageConfig, ServicePropertyChannel
)
from tqdm import tqdm
from docx import Document
import PyPDF2
import pypandoc
from pydub import AudioSegment
import yt_dlp
import colorama
from colorama import Fore, Style
from itertools import cycle
import re

colorama.init(autoreset=True)

def print_styled_message(message, color=Fore.WHITE, style=Style.NORMAL):
    """Imprime un mensaje con estilo en la consola."""
    print(color + style + message)

def sanitize_filename(filename):
    """Elimina caracteres especiales y emoticonos del nombre del archivo."""
    # Eliminar emoticonos y caracteres especiales
    sanitized = re.sub(r'[^\w\s-]', '', filename)
    # Reemplazar múltiples espacios por un solo espacio
    sanitized = re.sub(r'\s+', ' ', sanitized)
    return sanitized.strip()

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
            print_styled_message("\nNo se reconoció ninguna palabra.", Fore.RED, Style.BRIGHT)
        elif evt.result.reason == ResultReason.Canceled:
            cancellation_details = evt.result.cancellation_details
            if cancellation_details.reason == ResultReason.EndOfStream:
                print_styled_message("Transcripción completada.", Fore.GREEN, Style.BRIGHT)
            else:
                print_styled_message(f"Transcripción cancelada: {cancellation_details.reason}", Fore.RED, Style.BRIGHT)
                if cancellation_details.reason == ResultReason.Error:
                    print_styled_message(f"Error: {cancellation_details.error_details}", Fore.RED, Style.BRIGHT)
            done = True

    def stop_recognition(evt):
        nonlocal done
        done = True

    recognizer.recognized.connect(handle_final_result)
    recognizer.canceled.connect(handle_final_result)
    recognizer.session_stopped.connect(stop_recognition)

    recognizer.start_continuous_recognition()

    # Mostrar spinner durante la transcripción
    spinner = cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
    start_time = time.time()
    print_styled_message("Transcribiendo audio...", Fore.YELLOW, Style.BRIGHT)
    while not done:
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        milliseconds = (elapsed_time - int(elapsed_time)) * 1000
        spinner_char = next(spinner)
        if elapsed_time < 60:
            time_display = f"{elapsed_time:.2f} segundos transcurridos"
        else:
            time_display = f"{int(minutes)}m {int(seconds)}s {int(milliseconds)}ms transcurridos"
        print(Fore.YELLOW + Style.BRIGHT + f"{spinner_char} Transcribiendo... {time_display}", end='\r')
        time.sleep(0.1)

    recognizer.stop_continuous_recognition_async().get()

    with open(output_path, 'w', encoding='utf-8') as file:
        file.write(' '.join(all_results))

    print_styled_message("\nTranscripción completada y guardada en: " + output_path, Fore.GREEN, Style.BRIGHT)

def procesar_opciones_usuario(file_path, ai_client):
    """Procesa las opciones del usuario para el archivo de texto generado."""
    print_styled_message("Seleccione los resultados que desea visualizar (separados por comas):", Fore.CYAN, Style.BRIGHT)
    print_styled_message("1. Palabras clave del documento", Fore.CYAN, Style.BRIGHT)
    print_styled_message("2. Entidades", Fore.CYAN, Style.BRIGHT)
    print_styled_message("3. Enlaces", Fore.CYAN, Style.BRIGHT)
    print_styled_message("4. Resumen abstractivo", Fore.CYAN, Style.BRIGHT)
    user_choices = input("Ingrese los números de las opciones seleccionadas: ").split(',')

    text = read_file(file_path)
    text_parts = split_text(text, 5120)

    combined_text = ""
    all_phrases = set()
    all_entities = set()
    all_linked_entities = set()
    sentiments = []

    with tqdm(total=len(text_parts), desc=Fore.YELLOW + "Procesando solicitud...", ncols=120, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]', colour='green') as pbar:
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
                print_styled_message("...Is an error with code '{}' and message '{}'".format(
                    result.error.code, result.error.message), Fore.RED, Style.BRIGHT)

    # Crear la carpeta /summary si no existe
    summary_folder = 'summary'
    os.makedirs(summary_folder, exist_ok=True)

    # Generar el nombre del archivo de salida
    base_name = os.path.basename(file_path)
    output_file_name = f"summary_{os.path.splitext(base_name)[0]}.txt"
    output_file_path = os.path.join(summary_folder, output_file_name)

    # Escribir los resultados en el archivo de salida y mostrarlos en consola
    with open(output_file_path, 'w', encoding='utf-8') as output_file:
        output_file.write(f"Resultados para el documento: {base_name}\n")
        output_file.write(f"Idioma detectado: {detected_language.primary_language.name}\n")
        output_file.write(f"Sentimiento: {max(set(sentiments), key=sentiments.count)}\n")

        print_styled_message("\n-------------\nResultados para el documento: " + base_name, Fore.YELLOW, Style.BRIGHT)
        print_styled_message("\nIdioma detectado: {}".format(detected_language.primary_language.name), Fore.YELLOW, Style.BRIGHT)

        # Determinar el color del sentimiento
        sentimiento = max(set(sentiments), key=sentiments.count)
        if sentimiento == 'negative':
            sentimiento_color = Fore.RED
        elif sentimiento == 'positive':
            sentimiento_color = Fore.GREEN
        elif sentimiento == 'mixed':
            sentimiento_color = Fore.YELLOW
        else:  # neutral
            sentimiento_color = Fore.WHITE

        print_styled_message("\nSentimiento: {}".format(sentimiento), sentimiento_color, Style.BRIGHT)

        if '1' in user_choices and all_phrases:
            output_file.write("\nPalabras clave del documento:\n")
            print_styled_message("\nPalabras clave del documento:", Fore.YELLOW, Style.BRIGHT)
            for phrase in all_phrases:
                output_file.write(f"\t{phrase}\n")
                print_styled_message('\t{}'.format(phrase), Fore.CYAN, Style.NORMAL)

        if '2' in user_choices and all_entities:
            output_file.write("\nEntidades:\n")
            print_styled_message("\nEntidades:", Fore.YELLOW, Style.BRIGHT)
            for entity, category in all_entities:
                output_file.write(f"\t{entity} ({category})\n")
                print_styled_message('\t{} ({})'.format(entity, category), Fore.CYAN, Style.NORMAL)

        if '3' in user_choices and all_linked_entities:
            output_file.write("\nEnlaces:\n")
            print_styled_message("\nEnlaces:", Fore.YELLOW, Style.BRIGHT)
            for name, url in all_linked_entities:
                output_file.write(f"\t{name} ({url})\n")
                print_styled_message('\t{} ({})'.format(name, url), Fore.CYAN, Style.NORMAL)

        if '4' in user_choices:
            output_file.write("\nResumen abstractivo:\n")
            output_file.write(f"{summary}\n")
            print_styled_message("\nResumen abstractivo:", Fore.YELLOW, Style.BRIGHT)
            print_styled_message(f"{summary}\n", Fore.CYAN, Style.NORMAL)

    print_styled_message(f"\nResultados guardados en: {output_file_path}", Fore.GREEN, Style.BRIGHT)

def download_youtube_audio(url, output_folder):
    """Descarga el audio de un video de YouTube y lo guarda en formato .mp3."""

    def tqdm_hook(d):
        if d['status'] == 'downloading':
            pbar.update(d['downloaded_bytes'] - pbar.n)
            pbar.set_postfix(percentage=f"{d['_percent_str']}", speed=f"{d['_speed_str']}")
        elif d['status'] == 'finished':
            pbar.n = pbar.total
            pbar.close()
            print_styled_message("\nDescarga completada. Procesando el archivo de audio...", Fore.GREEN, Style.BRIGHT)

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': os.path.join(output_folder, '%(title)s.%(ext)s'),
        'quiet': True,
        'progress_hooks': [tqdm_hook]
    }

    print_styled_message("Iniciando la descarga del audio del video de YouTube...", Fore.CYAN, Style.BRIGHT)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(url, download=False)
        total_size = info_dict.get('filesize', 0)
        with tqdm(total=total_size, unit='B', unit_scale=True, desc=Fore.YELLOW + "Descargando audio", ncols=120, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]', colour='green') as pbar:
            result = ydl.extract_info(url, download=True)
            original_file_path = os.path.join(output_folder, f"{result['title']}.mp3")
            sanitized_title = sanitize_filename(result['title'])
            sanitized_file_path = os.path.join(output_folder, f"{sanitized_title}.mp3")
            if os.path.exists(original_file_path):
                os.rename(original_file_path, sanitized_file_path)
            return sanitized_file_path

def main():
    try:
        load_dotenv()
        ai_endpoint = os.getenv('AI_SERVICE_ENDPOINT')
        ai_key = os.getenv('AI_SERVICE_KEY')

        if not ai_endpoint or not ai_key:
            raise ValueError("Las variables de entorno AI_SERVICE_ENDPOINT y AI_SERVICE_KEY deben estar configuradas.")

        credential = AzureKeyCredential(ai_key)
        ai_client = TextAnalyticsClient(endpoint=ai_endpoint, credential=credential)

        print_styled_message("Seleccione la fuente de entrada:", Fore.CYAN, Style.BRIGHT)
        print_styled_message("1. Enlace de YouTube", Fore.CYAN, Style.BRIGHT)
        print_styled_message("2. Archivo de audio (mp3, wav, m4a)", Fore.CYAN, Style.BRIGHT)
        print_styled_message("3. Archivo de texto (txt, doc, pdf)", Fore.CYAN, Style.BRIGHT)
        source_choice = input("Ingrese el número de la opción seleccionada: ")

        if source_choice == '1':
            youtube_url = input("Ingrese la URL del video de YouTube: ")
            audio_folder = 'audio'
            file_path = download_youtube_audio(youtube_url, audio_folder)
            output_path = os.path.join('reviews', os.path.splitext(os.path.basename(file_path))[0] + '.txt')
            print_styled_message('\nTranscribiendo archivo de audio: ' + os.path.basename(file_path), Fore.CYAN, Style.BRIGHT)
            transcribe_audio(file_path, output_path)
            print_styled_message('Transcripción completada y guardada en: ' + output_path, Fore.GREEN, Style.BRIGHT)
            procesar_opciones_usuario(output_path, ai_client)

        elif source_choice == '2':
            audio_folder = 'audio'
            for file_name in os.listdir(audio_folder):
                if file_name == '.DS_Store':
                    continue

                file_path = os.path.join(audio_folder, file_name)
                output_path = os.path.join('reviews', os.path.splitext(file_name)[0] + '.txt')
                try:
                    print_styled_message('\nTranscribiendo archivo de audio: ' + file_name, Fore.CYAN, Style.BRIGHT)
                    transcribe_audio(file_path, output_path)
                    print_styled_message('Transcripción completada y guardada en: ' + output_path, Fore.GREEN, Style.BRIGHT)
                    procesar_opciones_usuario(output_path, ai_client)
                except Exception as e:
                    print_styled_message(f"Error al transcribir el archivo {file_name}: {e}", Fore.RED, Style.BRIGHT)

        elif source_choice == '3':
            reviews_folder = 'reviews'
            for file_name in os.listdir(reviews_folder):
                if file_name == '.DS_Store':
                    continue

                file_path = os.path.join(reviews_folder, file_name)
                try:
                    print_styled_message('\n-------------\n' + file_name, Fore.CYAN, Style.BRIGHT)
                    procesar_opciones_usuario(file_path, ai_client)
                except (UnicodeDecodeError, ValueError) as e:
                    print_styled_message(f"Error al leer el archivo {file_name}: {e}", Fore.RED, Style.BRIGHT)

    except Exception as ex:
        print_styled_message(str(ex), Fore.RED, Style.BRIGHT)

if __name__ == "__main__":
    main()
