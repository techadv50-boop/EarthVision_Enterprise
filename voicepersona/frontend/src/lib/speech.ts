export function speakText(text: string, lang = "en-US") {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = lang;
  utter.rate = 1;
  utter.pitch = 1;
  const voices = window.speechSynthesis.getVoices();
  const preferred =
    voices.find((v) => /en(-|_)?(us|gb|au)?/i.test(v.lang) && /natural|premium|enhanced/i.test(v.name)) ||
    voices.find((v) => v.lang.toLowerCase().startsWith("en"));
  if (preferred) utter.voice = preferred;
  window.speechSynthesis.speak(utter);
}

export async function playAudioUrl(url: string) {
  const audio = new Audio(url);
  await audio.play();
}
