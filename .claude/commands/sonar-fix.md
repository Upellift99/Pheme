Analyse les issues SonarQube du projet et corrige-les **TOUTES**, peu importe leur niveau de sévérité.

## Étapes

1. Récupérer toutes les issues SonarQube via `mcp__sonarqube__search_sonar_issues_in_projects` (project key : `Upellift99_Pheme_e9ed11f1-ecc0-4d23-bc08-88705135bbc5`)
2. Trier par sévérité : Blocker > Critical > Major > Minor > Info — mais **traiter chacune d'elles** sans en exclure aucune
3. Pour chaque issue (une à la fois) :
   - Lire le fichier concerné
   - Consulter la règle Sonar si besoin (`mcp__sonarqube__show_rule`)
   - Appliquer la correction
   - Mettre à jour les tests associés
   - Lancer les tests et le typecheck pertinents pour le projet (cf. `CLAUDE.md` ou `README`)
   - Proposer un commit : `fix(sonar): description courte (SXXXX)`
4. Attendre validation avant de passer à l'issue suivante
