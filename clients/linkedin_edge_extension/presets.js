(function(root){
  const PRESETS={
    'all-occupations-backfill':{
      plan:'all-occupations',keywords:'',occupationGroups:[],workplace:'any',workplaceModes:['any'],
      days:'7',maxJobs:'300',maxPages:'40',delay:'12',maxQueries:'10000',splitThreshold:'800',maxSplitDepth:'2',cooldownMinutes:'360',maxRetries:'2',
      includeRegions:true,excludes:'',strictTitle:false
    },
    'all-occupations-daily':{
      plan:'all-occupations',keywords:'',occupationGroups:[],workplace:'any',workplaceModes:['any'],
      days:'1',maxJobs:'300',maxPages:'40',delay:'12',maxQueries:'10000',splitThreshold:'800',maxSplitDepth:'2',cooldownMinutes:'360',maxRetries:'2',
      includeRegions:true,excludes:'',strictTitle:false
    },
    'us-data':{
      keywords:'Data Analyst\nData Analysis\nBusiness Intelligence Analyst\nData Scientist\nData Engineer\nAnalytics Engineer\nReporting Analyst\nMachine Learning Engineer\nProduct Analyst',
      location:'usa',workplace:'any',days:'7',maxJobs:'1000',maxPages:'40',delay:'5',
      excludes:'Financial Analyst,Laboratory Analyst,Security Analyst,Quality Analyst',strictTitle:true
    },
    'au-nursing':{
      keywords:'Registered Nurse',
      location:'australia',workplace:'any',days:'7',maxJobs:'1000',maxPages:'40',delay:'5',
      excludes:'Veterinary Nurse,Dental Nurse',strictTitle:false
    }
  };
  if(typeof module!=='undefined'&&module.exports)module.exports={PRESETS};else root.LINKEDIN_PRESETS=PRESETS;
})(typeof globalThis!=='undefined'?globalThis:this);
