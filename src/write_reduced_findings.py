"""Write a source-backed Greek findings note after the reduced series is verified."""
from pathlib import Path
import json
from datetime import datetime
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
R=ROOT/'results/campaign_20261102_reduced'
OUTPUT=Path(r'C:\Users\dioni\Documents\ChatGPT\Διπλοματική\output')

def main():
    v=json.loads((R/'validation.json').read_text())
    assert v['scope_completed'] and v['completed']==228
    f=pd.read_csv(R/'grouped_summary.csv')
    e=json.loads((R/'presentation_evidence.json').read_text())
    scope=json.loads((R/'scope.json').read_text());stop=json.loads((R/'stopped.json').read_text())
    minutes=(datetime.fromisoformat(stop['at'])-datetime.fromisoformat(scope['started_at'])).total_seconds()/60
    base=f[f.security_mode=='none']
    def get(dataset,n,topology,split='dirichlet',alpha=.5):
        a=base[(base.dataset==dataset)&(base.num_clients==n)&(base.topology==topology)&(base.split_type==split)]
        if split=='dirichlet':a=a[a.dirichlet_alpha==alpha]
        assert len(a)==1
        return a.iloc[0]
    names={'mnist':'MNIST','fashion_mnist':'Fashion-MNIST','cifar10':'CIFAR-10'}
    lines=['# Συμπληρωματικά αποτελέσματα — επιλεγμένη σειρά228 runs','',
        'Η περιορισμένη συγκριτική σειρά ολοκληρώθηκε και επαληθεύτηκε: **228/228 runs**, 76 ομάδες ρυθμίσεων, seeds1/2/3. Επαναχρησιμοποιήθηκαν119 ήδη ολοκληρωμένα runs και προστέθηκαν109 νέες εκτελέσεις. Τα αρχικά402 runs παραμένουν χωριστή σειρά· συνολικά υπάρχουν630 διακριτές ολοκληρωμένες εκτελέσεις. Το ευρύτερο πλάνο1.440 δεν έχει ολοκληρωθεί.',
        '',f'Η παρούσα εκτέλεση των109 νέων runs διήρκεσε **{minutes:.1f} λεπτά**, με δύο workers στο laptop. Μετά το τέλος της επιλεγμένης σειράς, η ευρύτερη καμπάνια παραμένει σε παύση.',
        '', '## Μεθοδολογία και εύρος', '',
        'Τα datasets παραμένουν πλήρη: MNIST/Fashion-MNIST60.000 train και10.000 test, CIFAR-1050.000 train και10.000 test. Χρησιμοποιήθηκαν MLP128, ReLU,20 rounds,1 local epoch, batch32 και SGD0,01. Οι180 βασικές εκτελέσεις καλύπτουν Dirichletα=0,5,5/10 clients, Caveman και Barabási–Albert, και τις πέντε μεθόδους προστασίας. Οι48 πρόσθετες εκτελέσεις αφορούν μόνο CIFAR-10 baseline: α=0,1/1,0 και IID/shards στις ίδιες τοπολογίες και αριθμούς clients.',
        '', 'Οι παρακάτω τιμές είναι mean ± **sample SD (ddof=1)** από τρία seeds. Η ακρίβεια είναι η μέση client accuracy στο πλήρες κοινό test set, μετά τον20ό γύρο. Η διασπορά των seeds περιλαμβάνει τις αλλαγές αρχικοποίησης και partition/γράφου που προβλέπει η μέθοδος.',
        '', '## Baseline με Dirichlet α=0,5', '', '| Dataset | Clients | Caveman (%) | Barabási–Albert (%) |','|---|---:|---:|---:|']
    deltas=[]
    for d in names:
        for n in [5,10]:
            a,b=get(d,n,'caveman'),get(d,n,'barabasi_albert');deltas.append(b.accuracy_mean-a.accuracy_mean)
            lines.append(f'| {names[d]} | {n} | {a.accuracy_mean:.2f} ± {a.accuracy_sd:.2f} | {b.accuracy_mean:.2f} ± {b.accuracy_sd:.2f} |')
    lines+=['',f'Στις έξι παραπάνω συγκρίσεις, η διαφορά Barabási−Caveman κυμαίνεται από{min(deltas):.2f} έως{max(deltas):.2f} ποσοστιαίες μονάδες. Η κατάταξη αλλάζει ανά περίπτωση και δεν στηρίζει γενική υπεροχή μίας τοπολογίας.',
            '', '## CIFAR-10: επίδραση κατανομής', '', '| Clients | Τοπολογία | IID (%) | Dir α=0,1 (%) | Dir α=0,5 (%) | Dir α=1,0 (%) | Shards (%) |','|---:|---|---:|---:|---:|---:|---:|']
    for n in [5,10]:
        for t in ['caveman','barabasi_albert']:
            rows=[get('cifar10',n,t,'iid'),get('cifar10',n,t,alpha=.1),get('cifar10',n,t),get('cifar10',n,t,alpha=1.),get('cifar10',n,t,'non_iid')]
            lines.append('| '+str(n)+' | '+t+' | '+' | '.join(f'{r.accuracy_mean:.2f} ± {r.accuracy_sd:.2f}' for r in rows)+' |')
    lines+=['', 'Οι τιμές α της Dirichlet επηρεάζουν τόσο το label skew όσο και το πλήθος δειγμάτων ανά client. Συνεπώς οι διαφορές δεν απομονώνουν μόνο έναν τύπο ετερογένειας. Τα αποτελέσματα CIFAR-10 αφορούν το συγκεκριμένο MLP και όριο20 γύρων· η συνεισφορά CNN ή μεγαλύτερου training budget χρειάζεται ξεχωριστή σύγκριση.',
        '', '## Προστασία και κόστος', '',
        f'Στα144 ζεύγη προστατευμένου run και baseline με ίδιο dataset, partition, seed, clients και τοπολογία, η μέγιστη απόλυτη διαφορά ακρίβειας είναι **{e["max_abs_protected_accuracy_delta_pp"]:.3f} ποσοστιαίες μονάδες**. Αυτό αποτελεί περιγραφικό εύρημα και όχι στατιστική απόδειξη ισοδυναμίας ή εγγύηση ιδιωτικότητας.',
        '', f'Η μέση μείωση του χρόνου επεξεργασίας HE στα{e["he_same_session_pairs"]} matched ζεύγη adaptive/selective του ίδιου session είναι **{e["paired_he_saving_percent_mean"]:.1f}%**. Πρόκειται για μέσο όρο ποσοστιαίων μειώσεων ανά ζεύγος, όχι για μείωση του συνολικού χρόνου training. Ένα ζεύγος άλλου session αποκλείστηκε από τη σύγκριση χρόνων.',
        '', '## Κείμενο για ένταξη στη διπλωματική', '',
        '> Λόγω του διαθέσιμου υπολογιστικού χρόνου, η συμπληρωματική αξιολόγηση περιορίστηκε σε228 εκτελέσεις με76 συνδυασμούς ρυθμίσεων και τρία seeds ανά συνδυασμό. Διατηρήθηκαν ολόκληρα τα datasets και οι αρχικές υπερπαράμετροι εκπαίδευσης. Η σειρά καλύπτει τις νέες τοπολογίες Caveman και Barabási–Albert με Dirichletα=0,5 στα τρία datasets και επεκτείνει τη μελέτη baseline του CIFAR-10 σε διαφορετικές κατανομές. Τα συμπεράσματα περιορίζονται στις εκτελεσμένες περιπτώσεις. Οι υπόλοιποι συνδυασμοί του ευρύτερου πλάνου παραμένουν μελλοντική εργασία.',
        '', '## Πηγές και αναπαραγωγή', '',
        '`results/campaign_20261102_reduced/scope.json`, `summary.csv`, `grouped_summary.csv`, `grouped_learning_curves.csv`, `accuracy_pairs.csv`, `he_pairs.csv`, `timing_by_session.csv`, `validation.json`. Τα raw metrics/metadata αναφέρονται από το manifest στην `campaign_20261020_full`.',
        '', 'Οι χρόνοι διαχωρίζονται ανά profile, περιβάλλον concurrency και execution session. Σε ομάδα που περνά σε άλλο session δεν παρουσιάζεται pooled timing mean/SD· οι υποομάδες με το πραγματικό n είναι στο timing_by_session.csv. Δεν συγχωνεύονται με τους αρχικούς serial χρόνους, τα οκτώ διερευνητικά CIFAR runs ή τα διαγνωστικά tests του Diogenis.']
    content='\n'.join(lines)+'\n'
    # Add normal spacing around the few compact numeric tokens in drafted copy.
    for a,b in [('σειρά228','σειρά 228'),('seeds1','seeds 1'),('Επαναχρησιμοποιήθηκαν119','Επαναχρησιμοποιήθηκαν 119'),('προστέθηκαν109','προστέθηκαν 109'),('αρχικά402','αρχικά 402'),('υπάρχουν630','υπάρχουν 630'),('πλάνο1.440','πλάνο 1.440'),('των109','των 109'),('MNIST60.000','MNIST 60.000'),('και10.000','και 10.000'),('CIFAR-1050.000','CIFAR-10 50.000'),('μετά τον20ό','μετά τον 20ό'),('Οι180','Οι 180'),('Οι48','Οι 48'),('Στα144','Στα 144'),('σε228','σε 228'),('με76','με 76'),('Dirichletα','Dirichlet α'),('μεγαλύτερουtraining','μεγαλύτερου training')]:content=content.replace(a,b)
    OUTPUT.mkdir(exist_ok=True,parents=True)
    (OUTPUT/'Secure_DFL_Results_228_20261102.md').write_text(content,encoding='utf-8')
    (R/'findings_el.md').write_text(content,encoding='utf-8')
    print('Greek findings note written; completed subset only.')

if __name__=='__main__':main()
