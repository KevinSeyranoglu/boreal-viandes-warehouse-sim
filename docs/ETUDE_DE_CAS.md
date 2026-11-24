# Étude de cas : décisions de personnel et de quai dans un centre de distribution sous froid

*Kevin Seyranoglu · [github.com/KevinSeyranoglu/boreal-viandes-warehouse-sim](https://github.com/KevinSeyranoglu/boreal-viandes-warehouse-sim) · [English version](CASE_STUDY.md)*

## La question

Un distributeur de viandes québécois expédie environ 25 000 caisses par jour, de trois chambres froides
vers 48 magasins. Chaque jour, ses gestionnaires décident combien de préparateurs mettre à l'horaire,
comment gérer le quai et quelles palettes solder avant leur péremption. Une mauvaise décision de
personnel coûte soit des salaires, soit des pénalités de livraison en retard (3 % de la valeur de la
commande, comme dans les programmes OTIF des détaillants).

Les données d'un vrai entrepôt sont confidentielles, alors j'ai construit l'entrepôt : une simulation de
tout le bâtiment (remorques, quai, rangement, préparation, chargement, quarts de travail, bris, rappels)
qui écrit les mêmes enregistrements qu'un système de gestion d'entrepôt, environ 700 000 lectures de
codes-barres par période de 180 jours. Comme le processus qui génère les données est connu, chaque
modèle peut être vérifié contre la réalité, et chaque politique peut être testée avant qu'on l'essaie
sur un vrai plancher.

## Ce que j'ai construit

- **Données :** un schéma en étoile de 27 tables par simulation, un extrait à largeur fixe de type
  IBM i (AS/400) lu par des programmes SAS, SQLite, DuckDB et Parquet.
- **Analytique :** 9 requêtes SQL d'indicateurs (OTIF, chaîne du froid, fiche fournisseur, traçabilité
  d'un lot rappelé), un export Power BI avec 17 mesures DAX et la valeur attendue de chacune, et un
  tableau de bord Streamlit bilingue.
- **Apprentissage automatique :** cinq modèles, chacun évalué en dollars contre la méthode qu'un centre
  de distribution utilise aujourd'hui : prévision de la demande, plan de main-d'œuvre, risque de
  commande en retard, risque de perte (périmés), alerte précoce en chambre froide.
- **Méthode :** découpage dans le temps (jamais aléatoire), vérification des fuites de données,
  5 graines aléatoires avec comparaisons appariées et intervalles à 95 %, et tests en boucle fermée qui
  relancent l'entrepôt avec un modèle aux commandes.
- **Génie logiciel :** Python, 72 tests automatisés exécutés par GitHub Actions à chaque envoi.

## Cinq constats

**1. Un plan de personnel par quart économise environ 3 500 $ par jour, sans perte de service.** En
boucle fermée sur 5 graines et 60 jours de test : les heures de préparation passent de 351 à 227 par
jour, les salaires et les pénalités baissent de **3 498 $ par jour** (intervalle à 95 % : −4 853 $ à
−2 143 $), et les livraisons à temps passent de 99,3 % à 99,7 %.

**2. Ça a commencé par un échec.** Mon premier modèle de main-d'œuvre planifiait un chiffre par jour et
promettait 815 $ par jour sur papier. Quand j'ai fait rouler l'entrepôt avec lui, il **perdait de
l'argent** : les livraisons à temps ont baissé de 3,9 points et les pénalités ont augmenté plus que les
salaires épargnés, avec chaque marge de sécurité essayée. Le modèle s'évaluait avec sa propre courbe de
capacité, ajustée sur des moyennes quotidiennes. L'analyse par quart a tout expliqué : les vagues des
départs de 3 h à 18 h tombent sur les quarts de nuit et de jour, alors que le quart de soir avait
18 préparateurs pour 5 % de la préparation. Couper tous les quarts de la même façon coupait aussi les
quarts chargés. La plus grande part du gain final vient de ce rééquilibrage; la prévision garde ensuite
1,7 point de plus de commandes à temps qu'une équipe fixe rééquilibrée, avec les mêmes heures.

**3. Une seule simulation ne prouve rien.** Avec une seule simulation, ajouter des préparateurs
semblait rentable. Sur cinq graines, c'était rentable avec une seule (−2 815 $ par jour en moyenne),
parce que le profit varie de ±1 632 $ par jour d'une simulation à l'autre. Réduire le personnel était
une perte nette avec chaque graine (−3 209 $ par jour).

**4. Le moment des opérations a battu l'ajout de personnel.** Quand chaque remorque a eu un
responsable (un réceptionnaire la décharge, un chargeur la charge, comme sur un vrai quai), les
livraisons à temps ont baissé de 3 à 4 points : les lectures de codes-barres montraient que le
chargement prenait 22 minutes après la dernière palette au lieu de 3. Ajouter des chargeurs
récupérait peu pour environ 1 000 $ par jour; lancer les vagues de préparation une heure plus tôt a
rétabli le service sans frais.

**5. Parfois, une règle est le bon modèle.** Une règle d'une ligne (« moins de 3 jours de durée de vie
à la réception ») a battu le modèle de pertes avec chaque graine, et chaque palette perdue venait de
chargements de volaille déjà vieillis : la solution est une clause au contrat du fournisseur.
Là où le signal est réel, l'apprentissage automatique a sa place : le modèle des commandes en retard
atteint une PR-AUC de 0,44 contre 0,05 pour la règle simple.

## Ce que je dirais à un gestionnaire

- Planifier le personnel par quart à partir de la prévision, en commençant par un projet pilote sur
  certains jours contre un groupe témoin.
- Ne pas se fier à la valeur hors ligne d'un modèle : tester la décision qu'il prend.
- Régler les pertes avec le fournisseur, pas avec un modèle.
- Un quai sur un seul mur (en U) fonctionne avec 6 portes de moins, au prix d'une attente de 8 minutes
  de plus pour les remorques à la guérite.

## Ce que j'ai appris

Le résultat le plus utile est venu d'un modèle qui a échoué : le tester en boucle fermée, puis chercher
pourquoi, a révélé le vrai problème. Mesurer l'incertitude (graines, différences appariées,
intervalles) a changé deux conclusions qu'une seule simulation aurait faussées. Et la méthode la plus
simple qui fonctionne devrait être celle qu'on déploie.

*Outils : Python (pandas, scikit-learn, DuckDB), SQL, Power BI et DAX, SAS, Streamlit, pygame, pytest,
GitHub Actions. L'entreprise, les usines et les magasins sont fictifs; les données sont simulées
volontairement.*
