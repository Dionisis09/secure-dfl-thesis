# Έτοιμο πακέτο για RTX4090 —20/50/100clients,3seeds

**Προετοιμασμένο, χωρίς έναρξη νέων πειραμάτων.** Απαιτείται πραγματικό
calibration στην επισκευασμένη4090 πριν εγκριθεί το τελικό εύρος.

Το scaling περιλαμβάνει **36περιπτώσεις**:

-20/50/100λογικούς clients.
-CIFAR-10, ring, Dirichlet alpha0,5.
-CNN και MLP με σχεδόν ίδιο πλήθος παραμέτρων.
-Baseline και adaptive hybrid, seeds1/2/3.
-20γύρους, πλήρες dataset και ίδιες ρυθμίσεις εκπαίδευσης.

Οι12περιπτώσεις των50clients δείχνουν στα ίδια jobs της κύριας σειράς.
Προστίθενται **24μοναδικά jobs**, χωρίς διπλές εκτελέσεις. Μαζί με τις τρεις
βασικές συγκρίσεις CIFAR/IID/shards/Dirichlet υπάρχουν114υποχρεωτικά jobs.
Τα492jobs του manifest είναι υποψήφια, όχι ήδη επιλεγμένα/ολοκληρωμένα.
Προαιρετικά datasets/τοπολογίες/sensitivity θα μπουν μόνο αν χωράνε.

## Κοινό όριο πέντε ημερών

Διατηρείται το αρχικό χρονόμετρο, χωρίς νέο πενθήμερο λόγω μεταφοράς:

-Έναρξη:7Νοεμβρίου2026,11:35:56UTC.
-Λήξη: **12Νοεμβρίου2026,13:35ώρα Ελλάδας**.
-Έως96ώρες εκτιμώμενης εργασίας, με24ώρες περιθώριο μέσα στις120ώρες.
-Το διαθέσιμο υπόλοιπο μειώνεται όσο περνάει ο χρόνος, μαζί με setup/calibration.

Το calibration μετρά χωριστά20/50/100clients στην4090. Δεν επεκτείνει
αυθαίρετα χρόνους των50στους100 και δεν εισάγει μετρήσεις του laptop.
Αν τα114υποχρεωτικά jobs δεν χωράνε, η μαζική εκτέλεση **δεν ξεκινά**.
Ο controller κρατά checkpoints και σταματά στο συνολικό όριο. Οι μερικές
ομάδες δεν παρουσιάζονται ως πλήρη αποτελέσματα3seeds.

## Μεταφορά αργότερα στον server

Αποσυμπίεσε στον ίδιο νέο φάκελο:

1. `Simulator4090_Scaling_20_50_100_3Seeds.zip` —κώδικας, manifest, οδηγίες.
2. `Simulator4090_Exact_Dataset_Cache.zip` —τα ακριβή3dataset caches.

Δεν ανεβάσαμε ακόμα το πακέτο ούτε ξεκινήσαμε installs/training στον server.
Μέσα στον νέο φάκελο εκτελούνται ρητά:

```bash
bash scripts/simulator4090.sh setup
bash scripts/simulator4090.sh check
bash scripts/simulator4090.sh calibrate
bash scripts/simulator4090.sh plan
# Συνέχεια μόνο αν το selected_plan.json έχει status: ready.
bash scripts/simulator4090.sh run
```

Το setup φτιάχνει ξεχωριστό Python3.12environment. Το check ελέγχει
CUDA/CKKS/cache χωρίς training. Το calibration έχει όριο μίας ώρας ανά εντολή
και συνεχίζεται ρητά με την ίδια εντολή αν χρειαστεί. Το default περιλαμβάνει
38benchmark jobs· κανένα δεν μετρά ως επιστημονικό seed1/2/3.

```bash
bash scripts/simulator4090.sh status
bash scripts/simulator4090.sh pause
# Αργότερα, χωρίς αλλαγή deadline:
bash scripts/simulator4090.sh clear-pause
bash scripts/simulator4090.sh run
bash scripts/simulator4090.sh summarize
```

Το `scaling_summary.json` δίνει mean/sampleSD μόνο σε πλήρεις ομάδες3seeds,
με χωριστά20/50/100clients και περιβάλλοντα. Οι50client αναφορές επαναχρησιμοποιούνται.
Τα αρχικά402/228runs και PowerPoint/Word/dashboard διατηρούνται όπως είναι.

Πρόκειται για single-GPU simulation με σταθερό συνολικό dataset, όχι100φυσικούς
υπολογιστές. Ο trainer βλέπει plaintext μοντέλα και ιδιωτικά CKKS κλειδιά,
όπως συμφωνήθηκε για το παλιό ύφος πειραμάτων. Υπάρχουν πραγματικές πράξεις
CKKS και masking, αλλά δεν προβάλλεται ανεξαρτησία/μυστικότητα από τον trainer.

Πέρασαν16tests. Το CKKS ελέγχθηκε αριθμητικά σε100λογικούς clients με2570τιμές
classifier· η πλήρης100client GPUεκπαίδευση/μνήμη/χρόνος παραμένει προς μέτρηση.
Αναλυτικά: `docs/SIMULATOR4090_SCALING_PLAN.md`.
