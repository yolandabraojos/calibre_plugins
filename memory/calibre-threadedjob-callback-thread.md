---
name: calibre-threadedjob-callback-thread
description: "Calibre ThreadedJob: el callback corre en el hilo worker, no en la GUI — hay que envolverlo con calibre.gui2.Dispatcher()."
metadata:
  node_type: memory
  type: project
  originSessionId: af3127c3-62bc-4690-952c-5088faaf4e57
---

Bug real encontrado y corregido en book_classifier v3.2.9 (2026-07-09): `action.py::_run_llm_rescue` pasaba `self._llm_job_done` directo como callback de `ThreadedJob(...)`. Confirmado en el código fuente de Calibre (`gui2/threaded_jobs.py`): `ThreadedJob.start_work()` llama a `self.callback(self)` DENTRO de `ThreadedJobWorker.run()`, que es un `threading.Thread` normal — el `JobManager` (gui2/jobs.py) solo usa un `QTimer` para refrescar la lista de tareas, nunca redespacha el callback al hilo Qt. O sea: **el callback de ThreadedJob se ejecuta siempre en el hilo worker, nunca en el hilo de la GUI**, salvo que se envuelva explícitamente.

Efecto del bug: `_llm_job_done` -> `_show_llm_results` creaba un `QDialog(self.gui)` y llamaba a `.exec()` desde el hilo worker, dando exactamente "QObject::setParent: Cannot set parent, new parent is in a different thread" y "QMetaMethod::invoke: Unable to invoke methods with return values in queued connections", y la ventana de resultados quedaba "(Not Responding)".

Fix: `calibre.gui2.Dispatcher` envuelve una función para que, se llame desde el hilo que se llame, se ejecute vía señal Qt en el hilo donde se creó el Dispatcher (la GUI, si se instancia ahí). Cambio de una línea: `ThreadedJob(..., Dispatcher(self._llm_job_done))` en vez de pasar `self._llm_job_done` pelado.

**Importante:** fix_metadata y extract_metadata YA hacían esto bien (`start_extract_threaded(gui, ids, Dispatcher(self._extraction_complete))`); ebook_comparator tiene su propio mecanismo de señal para lo mismo. Solo llm_jobs/action.py del book_classifier (código más nuevo, la capa de rescate LLM) se saltó el patrón. **Regla general para cualquier ThreadedJob nuevo en estos plugins: el callback SIEMPRE debe envolverse con `Dispatcher(...)` si toca Qt (diálogos) o la base de datos de Calibre.**

Ver [[book-classifier-hybrid-llm]] y [[calibre-plugins-repo-local]].
