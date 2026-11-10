# Ελαφρύτερη σειρά για το laptop — 10 Νοεμβρίου 2026

Η έκδοση χρησιμοποιεί την RTX 5070 Laptop 8 GB και έχει δικό της όριο
**24 ωρών**, με **4 ώρες περιθώριο μέσα στο όριο**. Είναι νέα, μικρότερη
σειρά συγκρίσεων. Δεν συνεχίζει ούτε αλλάζει το χρονόμετρο του server pack.

## Τι διατηρούμε

- Πλήρη δεδομένα εκπαίδευσης, ξεχωριστό validation και αμετάβλητο test set.
- Το υπάρχον residual CNN και το MLP με σχεδόν ίδιο πλήθος παραμέτρων.
- Τον ίδιο classifier 2.570 τιμών για την επιλεκτική HE.
- 20 γύρους, 1 τοπικό epoch, batch 128, AdamW lr 0,001 / weight decay 0,01.
- FP32, deterministic εκτέλεση, warmup/cosine και ίδιο CIFAR crop/flip.
- Τρία ανεξάρτητα επιστημονικά seeds: 1, 2, 3.
- Πραγματικές πράξεις CKKS και masking σε κάθε αντίστοιχο run.
- Checkpoints που επαναφέρουν μοντέλα, optimizers και RNG κάθε client.

Η ελάφρυνση προκύπτει από λιγότερους συνδυασμούς και **20 clients στην
κύρια σειρά**, αντί για 50/100 παντού. Δεν προκύπτει από μικρότερο dataset,
αφαίρεση seeds ή αλλαγή των αριθμών στα γραφήματα. Η αλλαγή του πλήθους των
clients αλλάζει την κατανομή και τη μάθηση, συνεπώς αυτή η σειρά αναφέρεται
ξεχωριστά από τις προηγούμενες. Δεν εγγυάται 80% accuracy ή ίδιο αποτέλεσμα
με 50 clients. Κρατά τη μεθοδολογική ποιότητα και τη δίκαιη σύγκριση.

## Προτεραιότητες

| Σειρά | Ρυθμίσεις | Runs |
|---|---|---:|
| Υποχρεωτική | CIFAR-10, 20 clients, ring, IID / Dirichlet α=0,5, 2 models × 5 modes × 3 seeds | 60 |
| Προαιρετική | Fashion-MNIST και MNIST, ίδια 2 splits, 20 clients, baseline/adaptive | 48 |
| Προαιρετική | CIFAR-10, Dirichlet α=0,5, 20 clients, Barabási–Albert / Caveman, baseline/adaptive | 24 |
| Προαιρετική | CIFAR-10, Dirichlet α=0,5, ring, 50 clients, baseline/adaptive | 12 |
| **Σύνολο υποψηφίων** | **Ολόκληρες ομάδες με δύο μοντέλα και τρία seeds** | **144** |

Τα πέντε modes στην κύρια σειρά είναι baseline, simple masking, pairwise
masking, selective HE και adaptive hybrid. Η HE αφορά τον classifier. Οι
100 clients και οι πλήρεις σαρώσεις alpha/HE-ratio/πυκνών γράφων δεν ανήκουν
σε αυτήν την έκδοση. Τα 144 είναι υποψήφια runs, όχι προεξοφλημένα αποτελέσματα.

## Επιλογή βάσει πραγματικού χρόνου

Το calibration έχει 22 jobs, seed 0 και δύο πλήρεις γύρους CIFAR-10:

- 20 clients / ring: και τα δύο μοντέλα με όλα τα πέντε modes.
- 20 clients / Barabási–Albert και Caveman: και τα δύο μοντέλα με baseline/adaptive.
- 50 clients / ring: και τα δύο μοντέλα με baseline/adaptive.

Το seed 0 δεν συμμετέχει στους μέσους όρους των επιστημονικών runs. Κάθε
τοπολογία και πλήθος clients έχει δική του μέτρηση. Δεν εισάγονται χρόνοι
της 4090 ή παλιά calibration άλλης έκδοσης/driver.

Το πλάνο αθροίζει setup, training, aggregation, validation/test και checkpoint
με **συντελεστή 2×**. Για τα προαιρετικά grayscale datasets χρησιμοποιεί
πρόβλεψη 1,5× του αντίστοιχου CIFAR κόστους. Είναι υπόθεση προγραμματισμού,
όχι πραγματική μέτρηση των grayscale runs. Η επιλογή βασίζεται μόνο σε κόστος,
όχι στην accuracy. Επιλέγονται έως 20 ώρες εκτιμώμενης εργασίας, αφαιρώντας
τον χρόνο που πέρασε από την έναρξη και κρατώντας 4 ώρες περιθώριο.

Οι προαιρετικές ομάδες αφαιρούνται ολόκληρες αν δεν χωράνε. Αν δεν χωράει η
βασική σειρά των 60, δεν εγκρίνεται η μαζική εκτέλεση. Ο controller σταματά
στο συνολικό όριο, με το τελευταίο έγκυρο checkpoint διαθέσιμο. Τα ολοκληρωμένα
runs δεν επαναλαμβάνονται. Αλλαγές σε source/cache/runtime/driver απορρίπτονται.

Οι αριθμοί του τελικά εγκεκριμένου πλάνου βρίσκονται στο
`laptop24_pack_20261110/selected_plan.json`. Η ζωντανή κατάσταση υπολογίζεται
από τα επαληθευμένα αρχεία αποτελεσμάτων, όχι από αποθηκευμένους μετρητές.
Το `state.json` περιέχει το πραγματικό start/deadline. Αναμονή και sleep του
laptop καταναλώνουν το ίδιο 24ωρο· η επανεκκίνηση δεν το μηδενίζει.

## Εκτέλεση στο υπάρχον project

Από τον φάκελο `secure-dfl-github-update`:

```powershell
# Κατάσταση και ήδη μετρημένο πλάνο — χωρίς training:
.\scripts\start_laptop24.ps1 status
.\scripts\start_laptop24.ps1 plan

# Ρητή έναρξη της κύριας σειράς, όταν το πλάνο είναι ready:
.\scripts\start_laptop24.ps1 run

# Παύση μετά τον τρέχοντα γύρο και αποθήκευση:
.\scripts\start_laptop24.ps1 pause

# Συνέχιση από checkpoint, με το ίδιο deadline:
.\scripts\start_laptop24.ps1 clear-pause
.\scripts\start_laptop24.ps1 run

# Mean/sample SD και καμπύλες validation από πραγματικά αποτελέσματα:
.\scripts\start_laptop24.ps1 summarize
```

Το άνοιγμα του φακέλου ή του dashboard δεν ξεκινά training. Η προεπιλογή του
PowerShell launcher είναι `status`. Μην ανοίγεις δεύτερο controller. Οι εντολές
`prepare`, `preflight`, `calibrate` υπάρχουν για ρητή προετοιμασία/έλεγχο. Ένα
calibration invocation έχει ανώτατο όριο 30 λεπτών μέσα στο συνολικό 24ωρο.

Το τοπικό `.venv` είναι ήδη διαθέσιμο. Για νέα αποσυμπίεση του source ZIP,
χρειάζονται Python 3.12, το ακριβές dataset cache και ξεχωριστό περιβάλλον:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-simulator50.txt
```

Το launcher στο source ZIP υποθέτει ότι το `.venv` και ο φάκελος
`data/simulator50-cache` υπάρχουν στη ρίζα. Το ZIP δεν περιέχει εγκατεστημένη
Python, datasets, ιδιωτικά κλειδιά ή checkpoints. Στο υφιστάμενο project δεν
χρειάζεται νέα εγκατάσταση ή νέα λήψη των datasets.

## Ερμηνεία αποτελεσμάτων

Το `summary.json` δίνει mean και **sample SD (n−1)** μόνο για ολοκληρωμένες
ομάδες seeds 1/2/3. Διατηρεί χωριστά model, dataset, split, topology, clients,
mode και runtime. Ελλιπείς ομάδες εμφανίζουν το πραγματικό n χωρίς επινοημένα
στατιστικά. Οι καμπύλες έχουν validation accuracy στους γύρους 5/10/15/20·
τα test scores υπολογίζονται μόνο στην τελική και στην καλύτερη validation
κατάσταση και δεν χρησιμοποιούνται για επιλογή πειραμάτων.

Πρόκειται για **trusted single-process simulation**: ο trainer βλέπει plaintext
μοντέλα και ιδιωτικά CKKS κλειδιά. Δεν τεκμηριώνεται μυστικότητα από τον trainer,
ανεξάρτητη εκτέλεση σε 20 φυσικά μηχανήματα ή μετρημένο WAN traffic. Τα bytes
επικοινωνίας είναι υπολογιστική εκτίμηση. Το ξεχωριστό proved/isolated protocol
και τα αρχικά 402/228 runs παραμένουν άθικτα.

Το server pack και ο κοινός υπολογιστικός του κώδικας δεν τροποποιήθηκαν.
Νέοι controller/launcher ανήκουν μόνο στη νέα σειρά. Word, PowerPoint και
dashboard δεν αντικαθίστανται με calibration ή μη ολοκληρωμένα νέα αποτελέσματα.
