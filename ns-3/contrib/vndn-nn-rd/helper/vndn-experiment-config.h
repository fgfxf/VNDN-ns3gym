#ifndef VNDN_EXPERIMENT_CONFIG_H
#define VNDN_EXPERIMENT_CONFIG_H

#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace vanet {

struct ExperimentRequest
{
  uint64_t sequence = 0;
  uint64_t sendTimeNs = 0;
};

/** Immutable inputs shared by the four algorithms in a comparison block. */
struct ExperimentConfig
{
  std::string scenario;
  std::string runId;
  std::string configPath;
  std::string sumoConfigPath;
  std::string routeFilePath;
  std::string requestPlanPath;
  std::string outputDirectory;
  bool trainingSnapshots = false;
  uint64_t measurementStartNs = 0;
  uint64_t measurementEndNs = 0;
  uint64_t drainEndNs = 0;
  uint32_t rngSeed = 1;
  uint64_t rngRun = 1;
  uint32_t sumoSeed = 1;
  uint32_t srandSeed = 1;
  std::vector<std::string> vehicleIds;
  std::map<std::string, std::vector<ExperimentRequest>> requestPlan;
};

ExperimentConfig LoadExperimentConfig (const std::string &path,
                                       const std::string &expectedScenario);

/** Write resolved settings without overwriting a prior experiment's evidence. */
void SaveEffectiveExperimentConfig (const ExperimentConfig &config, uint32_t strategy);
void SaveExperimentCompletion (const ExperimentConfig &config, bool complete,
                               uint64_t simulatedEndNs);
/** Existing TraCI launches SUMO through a shell; quote an external config path. */
std::string QuoteSumoConfigPath (const std::string &path);

} // namespace vanet

#endif
