import audioop
import wave
from queue import Queue
from threading import Thread
from typing import Literal, List
import subprocess
import json
from pydub import AudioSegment
from gtts import gTTS
from translate import Translator
from vosk import Model, KaldiRecognizer
import time
import pyaudio
from lib.types import DeviceInfo


class SpeechRecognition:
    def __init__(self):

        self.CHUNK = 1024
        self.AUDIO_FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.FRAME_RATE = 48000
        self.RECORD_SECONDS = 5  # Продолжительность записи аудиопотока

        self.input_device_index = 0  # Запустить SpeechRecognition.get_devices("Input") и выбрать индекс устройства для ввода
        self.output_device_index = 2  # Запустить SpeechRecognition.get_devices("Output") и выбрать индекс устройства для вывода
        self.messages = Queue()
        self.recordings = Queue()
        self.model = Model(model_path="./lib/vosk-model-small-ru-0.22")

    @staticmethod
    def get_devices(device_type: Literal["Output", "Input"]) -> List[DeviceInfo]:
        p = pyaudio.PyAudio()
        devices = []
        for i in range(p.get_device_count()):
            device_info = p.get_device_info_by_index(i)
            if device_info.get(f"max{device_type}Channels", 0) > 0:
                devices.append(device_info)
        p.terminate()
        return devices

    def start_recording(self):
        self.messages.put(True)
        record = Thread(target=self.__record_microphone)
        record.start()
        transcribe = Thread(target=self.__speech_recognition)
        transcribe.start()

    def __record_microphone(self, chunk=1024):
        p = pyaudio.PyAudio()

        stream = p.open(
            format=self.AUDIO_FORMAT,
            channels=self.CHANNELS,
            rate=self.FRAME_RATE,
            input=True,
            input_device_index=self.input_device_index,
            frames_per_buffer=chunk,
        )

        frames = []

        while not self.messages.empty():
            data = stream.read(chunk)
            sample_width = p.get_sample_size(pyaudio.paInt16)
            energy = audioop.rms(data, sample_width)
            if energy > 10:
                frames.append(data)
            if len(frames) >= (self.FRAME_RATE * self.RECORD_SECONDS) / chunk:
                self.recordings.put(frames.copy())
                frames = []
        stream.stop_stream()
        stream.close()
        p.terminate()

    @staticmethod
    def set_punctuation(text):
        cased = subprocess.check_output(
            "python recasepunc/recasepunc.py predict recasepunc/checkpoint",
            shell=True,
            text=True,
            input=text,
        )
        return cased

    @staticmethod
    def translate(text):
        translator = Translator(to_lang="en", from_lang="ru")
        return translator.translate(text)

    def __translate_to_speech_out(self, filename):
        wf = wave.open(filename, "rb")
        p = pyaudio.PyAudio()
        stream = p.open(
            format=p.get_format_from_width(wf.getsampwidth()),
            channels=wf.getnchannels(),
            rate=wf.getframerate(),
            output=True,
            output_device_index=self.output_device_index,
        )
        data = wf.readframes(self.CHUNK)
        while data:
            stream.write(data)
            data = wf.readframes(self.CHUNK)

        stream.stop_stream()
        stream.close()
        p.terminate()

    def __speech_recognition(self):

        rec = KaldiRecognizer(self.model, self.FRAME_RATE)
        rec.SetWords(True)

        while not self.messages.empty():
            frames = self.recordings.get()
            rec.AcceptWaveform(b"".join(frames))
            result = rec.Result()
            text = json.loads(result)["text"]
            # text = self.__set_punctuation(text) # Пока не требуется
            # Сюда можно встроить модуль прогнозарования следующих слов/предложений
            if len(text) > 0:
                tts = gTTS(text=self.translate(text), lang="en")
                tts.save("output.mp3")
                sound = AudioSegment.from_mp3("output.mp3")
                sound.export("output.wav", format="wav")
                self.__translate_to_speech_out("output.wav")
            time.sleep(1)
